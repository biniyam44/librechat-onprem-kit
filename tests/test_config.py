"""Static go-live checks on the kit's configuration.

Each test maps to a rule agreed for go-live (see docs/go-live-checklist.md).
They run in seconds, so they also run before every change to the config.
"""

import re

import pytest
import yaml

SECRET_KEYS = [
    "OPENID_CLIENT_SECRET",
    "OPENID_SESSION_SECRET",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "XAI_API_KEY",
    "CREDS_KEY",
    "CREDS_IV",
    "JWT_SECRET",
    "JWT_REFRESH_SECRET",
    "MEILI_MASTER_KEY",
    "ADMIN_PANEL_SESSION_SECRET",
]


class ComposeLoader(yaml.SafeLoader):
    """Safe YAML loader that understands Compose's !reset and !override tags."""


def _tagged(loader, suffix, node):
    if isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    elif isinstance(node, yaml.MappingNode):
        value = loader.construct_mapping(node, deep=True)
    else:
        value = loader.construct_scalar(node)
    return {"tag": suffix, "value": value}


ComposeLoader.add_multi_constructor("!", _tagged)


@pytest.fixture(scope="module")
def config(request):
    root = request.config.rootpath
    return yaml.safe_load((root / "librechat.yaml").read_text())


@pytest.fixture(scope="module")
def env(request):
    values = {}
    for line in (request.config.rootpath / ".env.onprem.example").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    return values


@pytest.fixture(scope="module")
def compose(request):
    text = (request.config.rootpath / "compose.onprem.yml").read_text()
    return yaml.load(text, Loader=ComposeLoader)["services"]


@pytest.fixture(scope="module")
def nginx(request):
    return (request.config.rootpath / "nginx" / "onprem.conf.template").read_text()


def test_sign_in_is_entra_id_only(config, env):
    assert config["registration"]["socialLogins"] == ["openid"]
    assert env["ALLOW_EMAIL_LOGIN"] == "false"
    assert env["ALLOW_REGISTRATION"] == "false"
    assert env["ALLOW_PASSWORD_RESET"] == "false"
    assert env["ALLOW_PASSKEY_LOGIN"] == "false"
    assert env["ALLOW_SOCIAL_LOGIN"] == "true"
    assert re.fullmatch(r"https://login\.microsoftonline\.com/[^/]+/v2\.0", env["OPENID_ISSUER"])
    # Only people with the app role can sign in.
    assert env["OPENID_REQUIRED_ROLE"] and env["OPENID_REQUIRED_ROLE_PARAMETER_PATH"] == "roles"


def test_only_approved_providers_and_models(config, env):
    assert set(env["ENDPOINTS"].split(",")) == {"anthropic", "openAI", "custom", "agents"}
    custom = config["endpoints"]["custom"]
    assert [e["name"] for e in custom] == ["xai"]
    for endpoint in custom:
        assert endpoint["models"]["fetch"] is False, "custom endpoints must list approved models only"
        assert endpoint["models"]["default"]
    assert env["ANTHROPIC_MODELS"] and env["OPENAI_MODELS"]
    approved = {
        "anthropic": set(env["ANTHROPIC_MODELS"].split(",")),
        "openAI": set(env["OPENAI_MODELS"].split(",")),
        "xai": set(custom[0]["models"]["default"]),
    }
    for spec in config["modelSpecs"]["list"]:
        preset = spec["preset"]
        assert preset["model"] in approved[preset["endpoint"]], f"{spec['name']} uses an unapproved model"


def test_provider_keys_stay_on_the_server(env):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY"):
        assert env[key] != "user_provided", f"{key} must be a server-side key"


def test_per_person_spend_limits_are_on(config):
    balance = config["balance"]
    assert balance["enabled"] is True
    assert balance["startBalance"] > 0 and balance["refillAmount"] > 0
    assert balance["autoRefillEnabled"] is True


def test_retention_applies_to_every_chat(config):
    interface = config["interface"]
    assert interface["retentionMode"] == "all"
    assert 1 <= interface["generalChatRetention"] <= 8760
    assert 1 <= interface["temporaryChatRetention"] <= 8760


def test_people_cannot_add_connectors_or_share_chats(config, env):
    interface = config["interface"]
    assert interface["mcpServers"] == {"use": True, "create": False, "share": False, "public": False}
    assert interface["sharedLinks"]["public"] is False and interface["sharedLinks"]["create"] is False
    assert interface["agents"]["public"] is False
    assert env["ALLOW_SHARED_LINKS"] == "false" and env["ALLOW_SHARED_LINKS_PUBLIC"] == "false"


def test_changes_need_human_approval_and_send_delete_are_denied(config):
    approval = config["endpoints"]["agents"]["toolApproval"]
    assert approval["enabled"] is True and approval["mode"] == "default"
    assert "mcp:*:*" in approval["ask"]
    assert {"mcp:*:delete_*", "mcp:*:send_*"} <= set(approval["deny"])
    assert approval["allowAlways"] is False
    for rule in approval["allow"]:
        tool = rule.rsplit(":", 1)[-1]
        assert tool.startswith(("get_", "list_", "search_")), f"{rule} would skip approval for a write"


def test_connectors_are_the_approved_ones_with_per_user_tokens(config):
    servers = config["mcpServers"]
    assert set(servers) == {"outlook-drafts", "pace-erp"}
    assert servers["outlook-drafts"]["headers"]["Authorization"] == "Bearer {{LIBRECHAT_GRAPH_ACCESS_TOKEN}}"
    assert "{{LIBRECHAT_OPENID_ACCESS_TOKEN}}" in servers["pace-erp"]["headers"]["Authorization"]


def test_internal_connectors_are_exempted_one_by_one(config):
    allowed = set(config["mcpSettings"]["allowedAddresses"])
    for name, server in config["mcpServers"].items():
        host_port = re.match(r"https?://([^/]+)", server["url"]).group(1)
        assert host_port in allowed, f"{name}: add {host_port} to mcpSettings.allowedAddresses"
    assert "allowedDomains" not in config["mcpSettings"], "allowedDomains would switch to strict mode"


def test_graph_scopes_never_include_mail_send(env):
    scopes = env["GRAPH_API_SCOPES"].split()
    assert "https://graph.microsoft.com/Mail.ReadWrite" in scopes
    assert not any("Send" in s for s in scopes)
    assert env["OPENID_REUSE_TOKENS"] == "true"


def test_only_nginx_is_published_and_only_on_the_lan_ip(compose):
    assert compose["api"]["ports"] == {"tag": "reset", "value": []}
    client_ports = compose["client"]["ports"]
    assert client_ports["tag"] == "override"
    for mapping in client_ports["value"]:
        assert mapping.startswith("${LAN_BIND_IP"), f"{mapping} is not bound to the internal address"
    for name, service in compose.items():
        if name not in ("api", "client"):
            assert "ports" not in service, f"{name} must not publish ports"


def test_connector_container_is_locked_down(compose):
    connector = compose["outlook-drafts"]
    assert connector["read_only"] is True
    assert "no-new-privileges:true" in connector["security_opt"]


def test_nginx_is_internal_only_and_streams_answers(root, nginx):
    assert nginx.count("include /etc/nginx/allow/") >= 3
    assert "it-only.conf" in nginx, "the admin panel must use the IT-only allow list"
    for allow_file in (root / "nginx" / "allow").glob("*.conf"):
        assert allow_file.read_text().strip().endswith("deny all;"), f"{allow_file.name} must end with deny all"
    assert "frame-ancestors 'self' ${INHOUSE_APP_ORIGIN}" in nginx
    assert "proxy_buffering off;" in nginx
    assert "ssl_protocols       TLSv1.2 TLSv1.3;" in nginx


def test_secrets_are_blank_in_the_example(env):
    for key in SECRET_KEYS:
        assert env[key] == "", f"{key} must be generated on the server, not stored in the example"


def test_real_secrets_cannot_be_committed(root):
    ignored = (root / ".gitignore").read_text().split()
    for entry in (".env", "certs/", "audit/", "*.archive.gz", "*.dump"):
        assert entry in ignored, f"{entry} must be in .gitignore"

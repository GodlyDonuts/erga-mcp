"""Optional project-scoped MCP host connections for Erga's local core."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

import questionary
from questionary import Choice

HostName = Literal[
    "codex",
    "claude-code",
    "opencode",
    "opencode-v2",
    "gemini-cli",
    "cursor",
    "github-copilot",
    "generic-mcp",
]
HostFormat = Literal["codex", "mcp-servers", "opencode", "opencode-v2"]


@dataclass(frozen=True)
class HostAdapter:
    id: HostName
    label: str
    executable: str | None
    format: HostFormat
    project_target: str
    include_stdio_type: bool = False


HOST_ADAPTERS: dict[HostName, HostAdapter] = {
    "codex": HostAdapter(
        id="codex",
        label="Codex / ChatGPT",
        executable="codex",
        format="codex",
        project_target=".codex/config.toml",
    ),
    "claude-code": HostAdapter(
        id="claude-code",
        label="Claude Code",
        executable="claude",
        format="mcp-servers",
        project_target=".mcp.json",
    ),
    "opencode": HostAdapter(
        id="opencode",
        label="OpenCode",
        executable="opencode",
        format="opencode",
        project_target="opencode.json",
    ),
    "opencode-v2": HostAdapter(
        id="opencode-v2",
        label="OpenCode V2",
        executable="opencode2",
        format="opencode-v2",
        project_target="opencode.json",
    ),
    "gemini-cli": HostAdapter(
        id="gemini-cli",
        label="Gemini CLI",
        executable="gemini",
        format="mcp-servers",
        project_target=".gemini/settings.json",
    ),
    "cursor": HostAdapter(
        id="cursor",
        label="Cursor",
        executable="cursor-agent",
        format="mcp-servers",
        project_target=".cursor/mcp.json",
    ),
    "github-copilot": HostAdapter(
        id="github-copilot",
        label="GitHub Copilot CLI",
        executable="copilot",
        format="mcp-servers",
        project_target=".mcp.json",
    ),
    "generic-mcp": HostAdapter(
        id="generic-mcp",
        label="Other MCP client using .mcp.json",
        executable=None,
        format="mcp-servers",
        project_target=".mcp.json",
    ),
}
SUPPORTED_HOSTS: tuple[HostName, ...] = tuple(HOST_ADAPTERS)
DEFAULT_SERVER_NAME = "erga-mcp"
DEFAULT_TOOL_PROFILE = "career"


@dataclass(frozen=True)
class HostConfiguration:
    host: HostName
    format: HostFormat
    target_path: Path
    server_name: str
    tool_profile: str
    content: str


@dataclass(frozen=True)
class HostConnectionResult:
    host: HostName
    label: str
    installed_on_path: bool | None
    target_path: str
    written: bool
    already_configured: bool
    model_api_required: bool = False


def host_adapter(host: HostName) -> HostAdapter:
    try:
        return HOST_ADAPTERS[host]
    except KeyError as error:
        raise ValueError(f"unsupported MCP host: {host}") from error


def resolve_server_command(explicit: Path | None = None) -> Path:
    """Resolve the installed server command without assuming a source checkout."""
    if explicit is not None:
        candidate = explicit.expanduser().absolute()
        if not candidate.is_file():
            raise FileNotFoundError(f"Erga MCP server command does not exist: {candidate}")
        return candidate
    discovered = shutil.which("erga-mcp")
    if discovered is not None:
        return Path(discovered).absolute()
    launcher_sibling = Path(sys.argv[0]).resolve().parent / "erga-mcp"
    if launcher_sibling.is_file():
        return launcher_sibling
    interpreter_sibling = Path(sys.executable).resolve().parent / "erga-mcp"
    if interpreter_sibling.is_file():
        return interpreter_sibling
    raise FileNotFoundError(
        "Could not find the erga-mcp executable. Run through `uv run erga`, install Erga, "
        "or pass --server-command."
    )


def _server(
    *,
    command: Path,
    server_args: tuple[str, ...],
    config_path: Path,
    include_stdio_type: bool,
) -> dict[str, object]:
    result: dict[str, object] = {
        "command": str(command),
        "args": list(server_args),
        "env": {
            "ERGA_MCP_CONFIG": str(config_path),
            "ERGA_MCP_TOOL_PROFILE": DEFAULT_TOOL_PROFILE,
        },
    }
    if include_stdio_type:
        result["type"] = "stdio"
    return result


def _codex_content(
    *,
    command: Path,
    server_args: tuple[str, ...],
    config_path: Path,
    server_name: str,
) -> str:
    quoted_args = ", ".join(json.dumps(value) for value in server_args)
    return (
        f"[mcp_servers.{json.dumps(server_name)}]\n"
        f"command = {json.dumps(str(command))}\n"
        f"args = [{quoted_args}]\n"
        "startup_timeout_sec = 60\n"
        "tool_timeout_sec = 300\n"
        'default_tools_approval_mode = "writes"\n\n'
        f"[mcp_servers.{json.dumps(server_name)}.env]\n"
        f"ERGA_MCP_CONFIG = {json.dumps(str(config_path))}\n"
        f"ERGA_MCP_TOOL_PROFILE = {json.dumps(DEFAULT_TOOL_PROFILE)}\n"
    )


def render_host_configuration(
    host: HostName,
    *,
    project_dir: Path,
    config_path: Path,
    server_command: Path,
    server_args: tuple[str, ...] = (),
    server_name: str = DEFAULT_SERVER_NAME,
) -> HostConfiguration:
    """Render one current, project-scoped MCP configuration without writing it."""
    adapter = host_adapter(host)
    project_dir = project_dir.expanduser().absolute()
    config_path = config_path.expanduser().absolute()
    server_command = server_command.expanduser().absolute()
    if not project_dir.is_dir():
        raise NotADirectoryError(f"Connection workspace does not exist: {project_dir}")
    if not config_path.is_file():
        raise FileNotFoundError(f"Erga core config does not exist: {config_path}")
    if not server_command.is_file():
        raise FileNotFoundError(f"Erga MCP server command does not exist: {server_command}")
    if not server_name.strip():
        raise ValueError("MCP server name cannot be empty")

    if adapter.format == "codex":
        content = _codex_content(
            command=server_command,
            server_args=server_args,
            config_path=config_path,
            server_name=server_name,
        )
    else:
        server = _server(
            command=server_command,
            server_args=server_args,
            config_path=config_path,
            include_stdio_type=adapter.include_stdio_type,
        )
        if adapter.format == "mcp-servers":
            document: dict[str, object] = {"mcpServers": {server_name: server}}
        elif adapter.format == "opencode":
            server.pop("type", None)
            server["type"] = "local"
            server["command"] = [str(server_command), *server_args]
            server["environment"] = server.pop("env")
            server["enabled"] = True
            server.pop("args", None)
            document = {
                "$schema": "https://opencode.ai/config.json",
                "mcp": {server_name: server},
            }
        else:
            server.pop("type", None)
            server["type"] = "local"
            server["command"] = [str(server_command), *server_args]
            server["environment"] = server.pop("env")
            server["cwd"] = str(project_dir)
            server.pop("args", None)
            document = {
                "$schema": "https://opencode.ai/config.json",
                "mcp": {"servers": {server_name: server}},
            }
        content = json.dumps(document, indent=2, sort_keys=True) + "\n"
    return HostConfiguration(
        host=host,
        format=adapter.format,
        target_path=project_dir / adapter.project_target,
        server_name=server_name,
        tool_profile=DEFAULT_TOOL_PROFILE,
        content=content,
    )


def _server_from_content(configuration: HostConfiguration, content: str) -> object:
    if configuration.format == "codex":
        document = tomllib.loads(content)
        servers = document.get("mcp_servers", {}) if isinstance(document, dict) else {}
    else:
        document = json.loads(content)
        if not isinstance(document, dict):
            return None
        if configuration.format == "mcp-servers":
            servers = document.get("mcpServers", {})
        else:
            mcp = document.get("mcp", {})
            if not isinstance(mcp, dict):
                return None
            servers = mcp.get("servers", {}) if configuration.format == "opencode-v2" else mcp
    return servers.get(configuration.server_name) if isinstance(servers, dict) else None


def _merge_json(configuration: HostConfiguration, existing: str) -> str:
    document = json.loads(existing) if existing.strip() else {}
    addition = json.loads(configuration.content)
    if not isinstance(document, dict):
        raise ValueError("existing host configuration must contain a JSON object")
    if configuration.format == "mcp-servers":
        servers = document.setdefault("mcpServers", {})
        generated = addition["mcpServers"][configuration.server_name]
    else:
        mcp = document.setdefault("mcp", {})
        if not isinstance(mcp, dict):
            raise ValueError("existing OpenCode mcp configuration must contain a JSON object")
        if configuration.format == "opencode-v2":
            servers = mcp.setdefault("servers", {})
            generated = addition["mcp"]["servers"][configuration.server_name]
        else:
            servers = mcp
            generated = addition["mcp"][configuration.server_name]
        document.setdefault("$schema", "https://opencode.ai/config.json")
    if not isinstance(servers, dict):
        raise ValueError("existing MCP server configuration must contain a JSON object")
    if configuration.server_name in servers:
        raise ValueError(
            f"MCP server {configuration.server_name!r} already exists with different settings; "
            "refusing to overwrite it"
        )
    servers[configuration.server_name] = generated
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _merge_codex(configuration: HostConfiguration, existing: str) -> str:
    if existing.strip():
        document = tomllib.loads(existing)
        servers = document.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise ValueError("existing Codex mcp_servers configuration must be a TOML table")
        if configuration.server_name in servers:
            raise ValueError(
                f"MCP server {configuration.server_name!r} already exists with different "
                "settings; refusing to overwrite it"
            )
    separator = "" if not existing else ("\n" if existing.endswith("\n") else "\n\n")
    return (
        existing
        + separator
        + "# Added by `erga connect`; project-local and optional.\n"
        + configuration.content
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}-",
        delete=False,
    ) as temporary:
        temporary.write(text)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _validate_target(configuration: HostConfiguration) -> None:
    project_dir = configuration.target_path
    for _part in Path(host_adapter(configuration.host).project_target).parts:
        project_dir = project_dir.parent
    resolved_project = project_dir.resolve()
    resolved_target = configuration.target_path.resolve(strict=False)
    try:
        resolved_target.relative_to(resolved_project)
    except ValueError as error:
        raise ValueError(
            "host configuration target must remain inside the selected workspace"
        ) from error
    if configuration.target_path.is_symlink():
        raise ValueError(
            f"refusing to replace a symlinked host configuration: {configuration.target_path}"
        )


def ensure_host_configuration(configuration: HostConfiguration) -> HostConnectionResult:
    """Create one host entry or safely reuse an identical shared entry."""
    target = configuration.target_path
    _validate_target(configuration)
    if configuration.format in {"opencode", "opencode-v2"} and not target.exists():
        alternatives = (
            target.with_suffix(".jsonc"),
            target.parent / ".opencode" / "opencode.json",
            target.parent / ".opencode" / "opencode.jsonc",
        )
        competing = next((path for path in alternatives if path.exists()), None)
        if competing is not None:
            raise ValueError(
                f"OpenCode configuration already exists at {competing}; refusing to create a "
                "second-precedence file. Merge the dry-run output there explicitly."
            )
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if existing and _server_from_content(configuration, existing) == _server_from_content(
        configuration, configuration.content
    ):
        written = False
        already_configured = True
    else:
        merged = (
            _merge_codex(configuration, existing)
            if configuration.format == "codex"
            else _merge_json(configuration, existing)
        )
        _atomic_write(target, merged)
        written = True
        already_configured = False
    adapter = host_adapter(configuration.host)
    return HostConnectionResult(
        host=configuration.host,
        label=adapter.label,
        installed_on_path=(
            shutil.which(adapter.executable) is not None if adapter.executable is not None else None
        ),
        target_path=str(target),
        written=written,
        already_configured=already_configured,
    )


def configure_hosts(
    hosts: tuple[HostName, ...],
    *,
    project_dir: Path,
    config_path: Path,
    server_command: Path | None = None,
    write: bool = True,
) -> list[dict[str, object]]:
    """Preview or connect any number of independent MCP hosts."""
    if not hosts:
        return []
    if "opencode" in hosts and "opencode-v2" in hosts:
        raise ValueError("select either OpenCode or OpenCode V2 for one workspace, not both")
    resolved_server = resolve_server_command(server_command)
    results: list[dict[str, object]] = []
    for host in dict.fromkeys(hosts):
        configuration = render_host_configuration(
            host,
            project_dir=project_dir,
            config_path=config_path,
            server_command=resolved_server,
        )
        if write:
            results.append(asdict(ensure_host_configuration(configuration)))
        else:
            adapter = host_adapter(host)
            results.append(
                {
                    "host": host,
                    "label": adapter.label,
                    "content": configuration.content,
                    "installed_on_path": (
                        shutil.which(adapter.executable) is not None
                        if adapter.executable is not None
                        else None
                    ),
                    "model_api_required": False,
                    "target_path": str(configuration.target_path),
                    "written": False,
                }
            )
    return results


def collect_optional_hosts(*, ask_to_connect: bool = True) -> tuple[HostName, ...]:
    """Offer zero, one, or multiple optional host connections."""
    if ask_to_connect and not bool(
        questionary.confirm(
            "Core setup is complete. Add optional coding-assistant connections now?",
            default=False,
        ).ask()
    ):
        return ()
    selected = questionary.checkbox(
        "Which MCP hosts should Erga connect?",
        choices=[Choice(adapter.label, value=adapter.id) for adapter in HOST_ADAPTERS.values()],
    ).ask()
    if selected is None:
        return ()
    return tuple(cast(list[HostName], selected))


def collect_connection_workspace(*, default: Path) -> Path:
    """Select the project whose local host configuration should receive Erga."""
    selected = questionary.path(
        "Project workspace for these optional connections:",
        default=str(default.expanduser().absolute()),
        only_directories=True,
        validate=lambda value: (
            True if Path(value).expanduser().is_dir() else "Choose an existing project directory."
        ),
    ).ask()
    if selected is None:
        raise RuntimeError("Optional host connection cancelled; Erga's core remains ready.")
    return Path(str(selected)).expanduser().absolute()

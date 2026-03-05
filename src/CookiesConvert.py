#!/usr/bin/env python3
"""Cookie converter with CLI, robust parsing and logging.

This tool reads one or more cookie files from an input directory, auto-
identifies the format (JSON, Netscape, Mozilla, or Selenium) and writes
converted copies in a desired format/extension.

The older interactive menus are still available but command-line
arguments have been added so the utility can be scripted or run non-
interactively.  Existing behaviour is preserved and many edge cases are
handled more gracefully.

Usage examples:
    python CookiesConvert.py                     # interactive mode
    python CookiesConvert.py -f netscape         # prompts for extension
    python CookiesConvert.py -f mozilla -e dat   # non-interactive
    python CookiesConvert.py -i mycookies -o out -f json --overwrite

"""

import argparse
import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Tuple

# constant lists used for validation/menus
FORMATS_INTERNAL = ["json", "netscape", "mozilla", "selenium"]
FORMATS_DISPLAY = ["Json", "NetScape", "Mozilla", "Selenium"]
# extensions we normally associate with a format (without leading dot)
EXT_DEFAULT: Dict[str, str] = {
    "json": "json",
    "netscape": "txt",
    "mozilla": "cookies",
    "selenium": "json",
}

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ---------------------------------------------------------------------------
# helper functions
# ---------------------------------------------------------------------------

def ensure_dirs(input_dir: Path, output_dir: Path) -> None:
    """Create input/output directories if they do not exist."""
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)


def load_text(path: Path) -> str:
    """Read the contents of ``path`` returning an empty string on failure."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:  # pragma: no cover - simple utility
        logger.error("Failed to read %s: %s", path, exc)
        return ""


def detect_format(text: str) -> Tuple[str, List[Dict]]:
    """Return ``(format, cookies)`` parsed from ``text``.

    The returned ``format`` will be one of the supported internal names or
    ``"unknown"`` if no recognised structure could be found.  ``cookies`` is
    always a list of dictionaries; the caller may ignore it when the format is
    unknown.
    """

    txt = text.strip()

    # JSON / Selenium-style list-of-dicts
    try:
        data = json.loads(txt)
        if isinstance(data, list) and all(isinstance(c, dict) for c in data):
            return "json", data
    except json.JSONDecodeError:  # not JSON
        pass

    # Netscape header
    if txt.startswith("# Netscape HTTP Cookie File"):
        cookies: List[Dict] = []
        for line in txt.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 7:
                continue
            domain, flag, path, secure, expires, name, value = parts
            try:
                cookies.append({
                    "domain": domain,
                    "flag": flag,
                    "path": path,
                    "secure": secure.upper() == "TRUE",
                    "expires": int(expires) if expires.isdigit() else 0,
                    "name": name,
                    "value": value,
                })
            except Exception:  # malformed entry, silently skip
                continue
        return "netscape", cookies

    # Mozilla - key=value; domain=...; ...
    if re.search(r"\bdomain=.*?;", txt):
        cookies = []
        for line in txt.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            try:
                first, *attrs = line.split(";")
                name, value = first.strip().split("=", 1)
                c = {
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": "",
                    "path": "/",
                    "expires": 0,
                    "secure": False,
                }
                for attr in attrs:
                    k, _, v = attr.strip().partition("=")
                    k = k.lower()
                    if k == "domain":
                        c["domain"] = v
                    elif k == "path":
                        c["path"] = v
                    elif k == "expires":
                        try:
                            c["expires"] = int(v)
                        except ValueError:
                            pass
                cookies.append(c)
            except Exception:  # ignore badly‑formed lines
                continue
        if cookies:
            return "mozilla", cookies

    return "unknown", []


def save_cookies(cookies: List[Dict], output_path: Path, formato: str) -> None:
    """Write ``cookies`` to ``output_path`` using ``formato``."""
    formato = formato.lower()
    with output_path.open("w", encoding="utf-8") as f:
        if formato in ("json", "selenium"):
            json.dump(cookies, f, indent=2, ensure_ascii=False)
        elif formato == "netscape":
            f.write("# Netscape HTTP Cookie File\n")
            for c in cookies:
                domain = c.get("domain", "")
                flag = "TRUE" if domain.startswith(".") else "FALSE"
                path = c.get("path", "/")
                secure = "TRUE" if c.get("secure", False) else "FALSE"
                expires = int(c.get("expires", 0) or 0)
                name = c.get("name", "")
                value = c.get("value", "")
                if not name or not value:
                    continue
                f.write(
                    f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n"
                )
        elif formato == "mozilla":
            for c in cookies:
                name = c.get("name", "")
                value = c.get("value", "")
                domain = c.get("domain", "")
                path = c.get("path", "/")
                expires = c.get("expires", 0)
                if not name or not value:
                    continue
                f.write(
                    f"{name}={value}; domain={domain}; path={path}; expires={expires}\n"
                )
        else:
            raise ValueError(f"Unsupported format: {formato}")


def choose_format_interactive() -> str:
    print("Choose the format for conversion:")
    for i, fmt in enumerate(FORMATS_DISPLAY, start=1):
        print(f"[{i}] {fmt}")
    while True:
        try:
            choice = int(input("Enter number: "))
            if 1 <= choice <= len(FORMATS_INTERNAL):
                return FORMATS_INTERNAL[choice - 1]
        except (ValueError, EOFError):
            pass
        print("Invalid selection, try again.")


def choose_extension_interactive() -> str:
    options = ["Txt", "Json", "Cookies", "Dat", "Custom"]
    print("\nChoose the file extension for the output files:")
    for i, ext in enumerate(options, start=1):
        print(f"[{i}] {ext}")
    while True:
        try:
            choice = int(input("Enter number: "))
            if 1 <= choice <= len(options):
                opt = options[choice - 1].lower()
                if opt == "custom":
                    custom = input("Extension (without dot): ").strip()
                    if custom and custom.isalnum():
                        return custom
                    print("Invalid custom extension.")
                else:
                    return opt
        except (ValueError, EOFError):
            pass
        print("Invalid selection, try again.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect and convert cookie files between formats."
    )
    parser.add_argument(
        "-i",
        "--input-dir",
        type=Path,
        default=Path("Cookies"),
        help="Directory containing cookie files (default: Cookies).",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("ConvertedCookies"),
        help="Directory for converted files.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=FORMATS_INTERNAL,
        help="Desired output format.",
    )
    parser.add_argument(
        "-e",
        "--extension",
        help="Output file extension (without dot).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files in output directory.",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Do not prompt; -f and -e must be provided.",
    )
    args = parser.parse_args()

    ensure_dirs(args.input_dir, args.output_dir)

    files = list(args.input_dir.glob("*"))
    if not files:
        logger.warning("No files found in %s", args.input_dir)
        return

    detected: List[Tuple[str, List[Dict]]] = []
    for f in files:
        if f.name.lower() == "help.txt":
            continue
        txt = load_text(f)
        fmt, cookies = detect_format(txt)
        logger.info("%s -> %s (%d cookies)", f.name, fmt, len(cookies))
        if fmt != "unknown" and cookies:
            detected.append((f.stem, cookies))

    if not detected:
        logger.warning("No cookie data detected.")
        return

    out_fmt = args.format
    if not out_fmt and not args.no_interactive:
        out_fmt = choose_format_interactive()
    if not out_fmt:
        parser.error("output format is required when --no-interactive")

    out_ext = args.extension
    if not out_ext:
        if args.no_interactive:
            parser.error("extension is required when --no-interactive")
        out_ext = choose_extension_interactive()

    out_ext = out_ext.lstrip(".")
    if not out_ext:
        out_ext = EXT_DEFAULT.get(out_fmt, out_ext)

    for name, cookies in detected:
        target = args.output_dir / f"{name}.{out_ext}"
        if target.exists() and not args.overwrite:
            logger.info("Skipping %s (already exists)", target.name)
            continue
        try:
            save_cookies(cookies, target, out_fmt)
            logger.info("Written %s", target.name)
        except Exception as exc:
            logger.error("Failed to write %s: %s", target.name, exc)

    logger.info("Conversion completed.")


if __name__ == "__main__":
    main()

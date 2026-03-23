from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from l10n_audit.core.audit_runtime import AuditRuntimeError


@dataclass
class Token:
    kind: str
    value: str
    position: int


class LaravelPhpParser:
    def __init__(self, source: str, path: Path) -> None:
        self.source = self._strip_comments(source)
        self.path = path
        self.length = len(self.source)
        self.index = 0

    def error(self, message: str) -> AuditRuntimeError:
        return AuditRuntimeError(f"{self.path}: {message}")

    @staticmethod
    def _strip_comments(source: str) -> str:
        result: list[str] = []
        index = 0
        length = len(source)
        in_string: str | None = None

        while index < length:
            ch = source[index]

            if in_string:
                result.append(ch)
                if ch == "\\" and index + 1 < length:
                    result.append(source[index + 1])
                    index += 2
                    continue
                if ch == in_string:
                    in_string = None
                index += 1
                continue

            if ch in {"'", '"'}:
                in_string = ch
                result.append(ch)
                index += 1
                continue

            if source.startswith("//", index):
                while index < length and source[index] != "\n":
                    result.append(" ")
                    index += 1
                continue

            if ch == "#":
                while index < length and source[index] != "\n":
                    result.append(" ")
                    index += 1
                continue

            if source.startswith("/*", index):
                result.extend([" ", " "])
                index += 2
                while index < length and not source.startswith("*/", index):
                    result.append("\n" if source[index] == "\n" else " ")
                    index += 1
                if index >= length:
                    raise AuditRuntimeError("Unterminated block comment.")
                result.extend([" ", " "])
                index += 2
                continue

            result.append(ch)
            index += 1

        return "".join(result)

    def skip_ws_and_comments(self) -> None:
        while self.index < self.length:
            if self.source.startswith("<?php", self.index):
                self.index += 5
                continue
            ch = self.source[self.index]
            if ch.isspace():
                self.index += 1
                continue
            break

    def peek(self) -> Token:
        saved = self.index
        token = self.next_token()
        self.index = saved
        return token

    def next_token(self) -> Token:
        self.skip_ws_and_comments()
        if self.index >= self.length:
            return Token("eof", "", self.index)

        if self.source.startswith("=>", self.index):
            token = Token("arrow", "=>", self.index)
            self.index += 2
            return token

        ch = self.source[self.index]
        if ch in "[](),;":
            token = Token(ch, ch, self.index)
            self.index += 1
            return token
        if ch in "\"'":
            return self.read_string()
        if ch.isdigit() or (ch == "-" and self.index + 1 < self.length and self.source[self.index + 1].isdigit()):
            return self.read_number()
        if ch.isalpha() or ch == "_":
            return self.read_identifier()
        raise self.error(f"Unsupported PHP token starting with {ch!r}.")

    def read_string(self) -> Token:
        quote = self.source[self.index]
        start = self.index
        self.index += 1
        chars: list[str] = []
        while self.index < self.length:
            ch = self.source[self.index]
            if ch == "\\":
                if self.index + 1 >= self.length:
                    raise self.error("Unterminated escape sequence in string.")
                nxt = self.source[self.index + 1]
                if quote == '"' and nxt == "$":
                    raise self.error("Interpolated PHP strings are not supported.")
                escape_map = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", "'": "'", '"': '"'}
                chars.append(escape_map.get(nxt, nxt))
                self.index += 2
                continue
            if quote == '"' and ch == "$":
                raise self.error("Interpolated PHP strings are not supported.")
            if ch == quote:
                self.index += 1
                return Token("string", "".join(chars), start)
            chars.append(ch)
            self.index += 1
        raise self.error("Unterminated string literal.")

    def read_number(self) -> Token:
        start = self.index
        if self.source[self.index] == "-":
            self.index += 1
        while self.index < self.length and self.source[self.index].isdigit():
            self.index += 1
        return Token("number", self.source[start:self.index], start)

    def read_identifier(self) -> Token:
        start = self.index
        while self.index < self.length and (self.source[self.index].isalnum() or self.source[self.index] == "_"):
            self.index += 1
        return Token("identifier", self.source[start:self.index], start)

    def expect(self, kind: str, value: str | None = None) -> Token:
        token = self.next_token()
        if token.kind != kind or (value is not None and token.value != value):
            expected = value if value is not None else kind
            raise self.error(f"Expected {expected}, found {token.kind}:{token.value!r}.")
        return token

    def parse(self) -> dict[str, object]:
        token = self.next_token()
        if token.kind != "identifier" or token.value != "return":
            raise self.error("Laravel translation file must start with a return statement.")
        value = self.parse_value()
        self.expect(";")
        if self.next_token().kind != "eof":
            raise self.error("Unexpected trailing tokens after return array.")
        if not isinstance(value, dict):
            raise self.error("Laravel translation file must return an array.")
        return value

    def parse_value(self) -> object:
        token = self.peek()
        if token.kind == "[":
            return self.parse_array()
        if token.kind == "identifier" and token.value == "array":
            self.next_token()
            value = self.parse_array(closing=")", consume_opener=True)
            return value
        if token.kind == "string":
            return self.next_token().value
        raise self.error("Only string values and nested arrays are supported in Laravel translation files.")

    def parse_array(self, closing: str = "]", consume_opener: bool = False) -> dict[str, object]:
        opener = "[" if closing == "]" else "("
        if consume_opener:
            self.expect(opener)
        else:
            self.expect(opener)
        items: dict[str, object] = {}
        implicit_index = 0
        first = True
        while True:
            token = self.peek()
            if token.kind == closing:
                self.next_token()
                return items
            if not first:
                self.expect(",")
                token = self.peek()
                if token.kind == closing:
                    self.next_token()
                    return items
            first = False

            key_token = self.peek()
            if key_token.kind in {"string", "number"}:
                parsed_key = self.next_token().value
                if self.peek().kind == "arrow":
                    self.next_token()
                    value = self.parse_value()
                    items[str(parsed_key)] = value
                    continue
                items[str(implicit_index)] = parsed_key
                implicit_index += 1
                continue
            raise self.error("Only string or numeric array keys are supported.")


def _flatten_group(prefix: str, value: object, output: dict[str, str], path: Path) -> None:
    if isinstance(value, str):
        output[prefix] = value
        return
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            child_prefix = f"{prefix}.{child_key}" if prefix else str(child_key)
            _flatten_group(child_prefix, child_value, output, path)
        return
    raise AuditRuntimeError(f"{path}: Unsupported non-string translation leaf under key '{prefix}'.")


def _load_php_group(path: Path) -> dict[str, str]:
    parser = LaravelPhpParser(path.read_text(encoding="utf-8"), path)
    payload = parser.parse()
    group = path.stem
    flattened: dict[str, str] = {}
    _flatten_group(group, payload, flattened, path)
    return flattened


def load_laravel_php_locale(path: Path) -> dict[str, object]:
    if not path.exists():
        raise AuditRuntimeError(f"Locale source not found: {path}")
    if path.is_file():
        if path.suffix != ".php":
            raise AuditRuntimeError(f"Laravel PHP locale source must be a .php file or locale directory: {path}")
        return _load_php_group(path)

    php_files = sorted(child for child in path.iterdir() if child.is_file() and child.suffix == ".php")
    if not php_files:
        raise AuditRuntimeError(f"No Laravel PHP translation files found in locale directory: {path}")

    merged: dict[str, str] = {}
    for php_file in php_files:
        for key, value in _load_php_group(php_file).items():
            if key in merged:
                raise AuditRuntimeError(f"Duplicate normalized translation key '{key}' produced from {php_file}.")
            merged[key] = value
    return merged

import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
SKIP_TAGS = {"script", "style", "template"}


class MockupParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.title = ""
        self.headings = []
        self.labels = []
        self.fields = []
        self.actions = []
        self.links = []
        self.text = []
        self.has_script = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        hidden = tag in SKIP_TAGS or "hidden" in attributes or any(frame["hidden"] for frame in self.stack)
        self.has_script = self.has_script or tag == "script"
        frame = {"tag": tag, "attrs": attributes, "hidden": hidden, "text": []}
        if not hidden and tag in {"input", "select", "textarea"}:
            self.fields.append({
                "tag": tag, "id": attributes.get("id", ""), "name": attributes.get("name", ""),
                "type": attributes.get("type", "text" if tag == "input" else tag),
                "label_hint": attributes.get("aria-label", ""), "placeholder": attributes.get("placeholder", ""),
                "required_attribute": "required" in attributes, "disabled_attribute": "disabled" in attributes,
            })
        if tag not in VOID_TAGS:
            self.stack.append(frame)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if any(frame["hidden"] for frame in self.stack):
            return
        value = " ".join(data.split())
        if not value:
            return
        if not any(frame["tag"] in {"title", "head"} for frame in self.stack):
            self.text.append(value)
        for frame in self.stack:
            if frame["tag"] in {"title", "h1", "h2", "h3", "h4", "label", "button", "a"} or frame["attrs"].get("role") == "button":
                frame["text"].append(value)

    def handle_endtag(self, tag):
        position = next((index for index in range(len(self.stack) - 1, -1, -1) if self.stack[index]["tag"] == tag), None)
        if position is None:
            return
        closed = self.stack[position:]
        self.stack = self.stack[:position]
        for frame in closed:
            if frame["hidden"]:
                continue
            attributes = frame["attrs"]
            text = " ".join(frame["text"])
            record = {"tag": frame["tag"], "id": attributes.get("id", ""), "text": text}
            if frame["tag"] == "title":
                self.title = text
            if frame["tag"] in {"h1", "h2", "h3", "h4"}:
                self.headings.append(record)
            if frame["tag"] == "label":
                self.labels.append({**record, "for": attributes.get("for", "")})
            if frame["tag"] == "button" or attributes.get("role") == "button":
                self.actions.append({**record, "label_hint": attributes.get("aria-label", ""), "disabled_attribute": "disabled" in attributes})
            if frame["tag"] == "a":
                raw = attributes.get("href", "")
                parsed = urlsplit(raw)
                safe_href = urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", parsed.fragment)) if parsed.scheme in {"http", "https"} else (raw.split("?", 1)[0] if not parsed.scheme else "[非導覽網址已省略]")
                self.links.append({**record, "href_hint": safe_href})


def inspect_file(path, encoding="utf-8"):
    path = Path(path)
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("HTML超過靜態工具的5MiB讀取上限；請分頁或人工判讀。")
    data = path.read_bytes()
    parser = MockupParser()
    parser.feed(data.decode(encoding))
    parser.close()
    labels = {item["for"]: item["text"] for item in parser.labels if item["for"]}
    for field in parser.fields:
        field["label_hint"] = field["label_hint"] or labels.get(field["id"], "")
    return {
        "input_filename": path.name, "sha256": hashlib.sha256(data).hexdigest(),
        "inspection": "static_only", "customer_approval": "not_inferred",
        "title": parser.title, "headings": parser.headings, "fields": parser.fields,
        "actions": parser.actions, "navigation": parser.links, "text_fragments": parser.text,
        "has_script": parser.has_script,
        "limitations": ["未執行JavaScript、未載入CSS或外部資源，不能證明實際可見性、互動、權限或客戶核准。", "未收錄輸入value及網址query，避免把秘密或示例值帶入需求。"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--encoding", default="utf-8")
    args = parser.parse_args()
    try:
        result = inspect_file(args.input, args.encoding)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, UnicodeError) as exception:
        print(str(exception))
        return 1
    print(json.dumps({"inspection": result["inspection"], "fields": len(result["fields"]), "actions": len(result["actions"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

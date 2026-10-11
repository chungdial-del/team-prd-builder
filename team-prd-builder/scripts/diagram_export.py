import html
import math
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

PALETTE = {
    "blue": ("#eaf2ff", "#5272a8", "#182c4b"),
    "green": ("#e9f5ef", "#4b8d70", "#174832"),
    "orange": ("#fff3e0", "#bc8645", "#6b4216"),
    "gray": ("#f5f7fa", "#9ba8ba", "#39475c"),
    "navy": ("#172c49", "#172c49", "#ffffff"),
}


def line_units(text):
    return sum(2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1 for character in text)


def wrapped(text, width, size=14):
    maximum = max(4, int((width - 20) / (size * 0.55)))
    lines = []
    for paragraph in text.split("\n"):
        current = ""
        for character in paragraph:
            if current and line_units(current + character) > maximum:
                lines.append(current)
                current = ""
            current += character
        lines.append(current)
    return lines


def diagram_svg(diagram):
    esc = html.escape
    identifier = diagram["id"]
    font_size = diagram.get("font_size", 14)
    line_height = font_size * 1.4
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="' + esc(diagram["title"], quote=True) + '" viewBox="0 0 ' + str(diagram["width"]) + " " + str(diagram["height"]) + '">']
    parts.append('<defs><marker id="' + identifier + '-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#52657d"/></marker></defs>')
    parts.append('<rect width="100%" height="100%" fill="white"/>')

    def vertex(node):
        fill, stroke, ink = PALETTE[node["tone"]]
        xpos, ypos, width, height = (node[key] for key in ("x", "y", "width", "height"))
        shape = node["shape"]
        if shape == "diamond":
            points = [(xpos + width / 2, ypos), (xpos + width, ypos + height / 2), (xpos + width / 2, ypos + height), (xpos, ypos + height / 2)]
            parts.append('<polygon points="' + " ".join(str(first) + "," + str(second) for first, second in points) + '" fill="' + fill + '" stroke="' + stroke + '"/>')
        elif shape != "text":
            parts.append('<rect x="' + str(xpos) + '" y="' + str(ypos) + '" width="' + str(width) + '" height="' + str(height) + '" rx="' + ("0" if shape == "group" else "8") + '" fill="' + fill + '" stroke="' + stroke + '"' + (' stroke-dasharray="6 4"' if shape == "group" else "") + "/>")
        if shape == "text":
            ink = "#182c4b"
        lines = wrapped(node["label"], width if shape != "diamond" else width * 0.7, font_size)
        top = ypos + font_size + 9 if shape == "group" else ypos + (height - (len(lines) - 1) * line_height) / 2 + font_size * 0.35
        anchor = "start" if shape == "group" else "middle"
        center = xpos + 12 if shape == "group" else xpos + width / 2
        for index, line in enumerate(lines):
            parts.append('<text x="' + str(center) + '" y="' + str(top + index * line_height) + '" text-anchor="' + anchor + '" font-size="' + str(font_size) + '" fill="' + ink + '">' + esc(line) + "</text>")

    parts.append('<g font-family="Arial, Microsoft JhengHei, PingFang TC, sans-serif">')
    for node in diagram["nodes"]:
        if node["shape"] == "group":
            vertex(node)
    for edge in diagram["edges"]:
        style = edge["style"]
        points = " ".join(str(point["x"]) + "," + str(point["y"]) for point in edge["points"])
        attributes = ' stroke-dasharray="7 5"' if style in {"return", "lifeline"} else ""
        if style != "lifeline":
            attributes += ' marker-end="url(#' + identifier + '-arrow)"'
        parts.append('<polyline points="' + points + '" fill="none" stroke="#52657d" stroke-width="1.5"' + attributes + "/>")
        if edge.get("label"):
            size = label_size(diagram, edge)
            label_width = line_units(edge["label"]) * size * 0.55 + 12
            parts.append('<rect x="' + str(edge["label_x"] - label_width / 2) + '" y="' + str(edge["label_y"] - size) + '" width="' + str(label_width) + '" height="' + str(size + 5) + '" fill="white"/>')
            parts.append('<text x="' + str(edge["label_x"]) + '" y="' + str(edge["label_y"]) + '" text-anchor="middle" font-size="' + str(size) + '" fill="#39475c">' + esc(edge["label"]) + "</text>")
    for node in diagram["nodes"]:
        if node["shape"] != "group":
            vertex(node)
    parts.append("</g></svg>")
    return "".join(parts)


def diagram_xml(diagrams):
    root = ET.Element("mxfile", host="app.diagrams.net", version="24.7.17", compressed="false", type="device")
    for diagram in diagrams:
        font_size = diagram.get("font_size", 14)
        page = ET.SubElement(root, "diagram", id=diagram["id"], name=diagram["title"])
        graph = ET.SubElement(page, "mxGraphModel", dx="1200", dy="900", grid="1", gridSize="10", guides="1", tooltips="1", connect="1", arrows="1", fold="1", page="1", pageScale="1", pageWidth=str(diagram["width"]), pageHeight=str(diagram["height"]), math="0", shadow="0")
        cells = ET.SubElement(graph, "root")
        ET.SubElement(cells, "mxCell", id="0")
        ET.SubElement(cells, "mxCell", id="1", parent="0")
        nodes = {node["id"]: node for node in diagram["nodes"]}

        def vertex(node):
            fill, stroke, ink = PALETTE[node["tone"]]
            shape = node["shape"]
            style = "html=0;whiteSpace=wrap;fontFamily=Arial;fontSize=" + str(font_size) + ";spacing=8;align=center;verticalAlign=middle;strokeWidth=1;"
            if shape == "diamond":
                style += "rhombus;"
            elif shape == "text":
                style += "text;fillColor=none;strokeColor=none;"
                ink = "#182c4b"
            else:
                style += "rounded=" + ("0" if shape == "group" else "1") + ";fillColor=" + fill + ";strokeColor=" + stroke + ";"
            if shape == "group":
                style += "dashed=1;align=left;verticalAlign=top;"
            style += "fontColor=" + ink + ";"
            cell = ET.SubElement(cells, "mxCell", id=node["id"], value=node["label"], style=style, vertex="1", parent="1")
            ET.SubElement(cell, "mxGeometry", x=str(node["x"]), y=str(node["y"]), width=str(node["width"]), height=str(node["height"]), **{"as": "geometry"})

        for node in diagram["nodes"]:
            if node["shape"] == "group":
                vertex(node)
        for edge in diagram["edges"]:
            style = "edgeStyle=none;html=0;rounded=0;strokeColor=#52657d;strokeWidth=1.5;fontFamily=Arial;fontSize=" + str(label_size(diagram, edge)) + ";fontColor=#39475c;labelBackgroundColor=#ffffff;endArrow=" + ("none" if edge["style"] == "lifeline" else "classic") + ";"
            if edge["style"] in {"return", "lifeline"}:
                style += "dashed=1;"
            attrs = {"id": edge["id"], "value": edge.get("label", ""), "style": style, "edge": "1", "parent": "1"}
            if edge.get("source"):
                attrs.update(source=edge["source"], target=edge["target"])
                for endpoint, prefix, point in (("source", "exit", edge["points"][0]), ("target", "entry", edge["points"][-1])):
                    node = nodes[edge[endpoint]]
                    attrs["style"] += prefix + "X=" + str((point["x"] - node["x"]) / node["width"]) + ";" + prefix + "Y=" + str((point["y"] - node["y"]) / node["height"]) + ";" + prefix + "Perimeter=0;"
            cell = ET.SubElement(cells, "mxCell", **attrs)
            geometry = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
            if not edge.get("source"):
                for point, name in ((edge["points"][0], "sourcePoint"), (edge["points"][-1], "targetPoint")):
                    ET.SubElement(geometry, "mxPoint", x=str(point["x"]), y=str(point["y"]), **{"as": name})
            if len(edge["points"]) > 2:
                array = ET.SubElement(geometry, "Array", **{"as": "points"})
                for point in edge["points"][1:-1]:
                    ET.SubElement(array, "mxPoint", x=str(point["x"]), y=str(point["y"]))
            if edge.get("label"):
                geometry.set("x", "-1")
                geometry.set("y", "0")
                ET.SubElement(geometry, "mxPoint", x=str(edge["label_x"] - edge["points"][0]["x"]), y=str(edge["label_y"] - edge["points"][0]["y"]), **{"as": "offset"})
        for node in diagram["nodes"]:
            if node["shape"] != "group":
                vertex(node)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def label_size(diagram, edge):
    preferred = diagram.get("label_font_size", 13)
    span = abs(edge["points"][-1]["x"] - edge["points"][0]["x"])
    return min(preferred, max(10, (span - 16) / max(1, line_units(edge.get("label", "")) * 0.55))) if span > 100 else preferred


def resolve_font(font_file=None):
    candidates = [font_file] if font_file else [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "C:/Windows/Fonts/msjh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise FileNotFoundError("缺少可用CJK字型；以 --font-file 指定字型，不生成缺字插圖。")


def diagram_png(diagram, destination, font_file=None):
    from PIL import Image, ImageDraw, ImageFont

    scale = 3
    image = Image.new("RGB", (int(diagram["width"] * scale), int(diagram["height"] * scale)), "white")
    draw = ImageDraw.Draw(image)
    font_path = resolve_font(font_file)
    font_size = diagram.get("font_size", 14)
    line_height = font_size * 1.4
    font = ImageFont.truetype(font_path, round(font_size * scale))

    def position(point):
        return (point[0] * scale, point[1] * scale)

    def vertex(node):
        fill, stroke, ink = PALETTE[node["tone"]]
        xpos, ypos, width, height = (node[key] for key in ("x", "y", "width", "height"))
        shape = node["shape"]
        box = (xpos * scale, ypos * scale, (xpos + width) * scale, (ypos + height) * scale)
        if shape == "diamond":
            points = [(xpos + width / 2, ypos), (xpos + width, ypos + height / 2), (xpos + width / 2, ypos + height), (xpos, ypos + height / 2)]
            draw.polygon([position(point) for point in points], fill=fill, outline=stroke, width=scale)
        elif shape != "text":
            draw.rounded_rectangle(box, radius=0 if shape == "group" else 8 * scale, fill=fill, outline=stroke, width=scale)
        if shape == "text":
            ink = "#182c4b"
        lines = wrapped(node["label"], width if shape != "diamond" else width * 0.7, font_size)
        top = ypos + font_size + 9 if shape == "group" else ypos + (height - (len(lines) - 1) * line_height) / 2 + font_size * 0.35
        center = xpos + 12 if shape == "group" else xpos + width / 2
        for index, line in enumerate(lines):
            draw.text(position((center, top + index * line_height)), line, font=font, fill=ink, anchor="ls" if shape == "group" else "ms")

    for node in diagram["nodes"]:
        if node["shape"] == "group":
            vertex(node)
    for edge in diagram["edges"]:
        points = [(point["x"], point["y"]) for point in edge["points"]]
        for first, second in zip(points, points[1:]):
            distance = math.hypot(second[0] - first[0], second[1] - first[1])
            if edge["style"] in {"return", "lifeline"} and distance:
                offset = 0
                while offset < distance:
                    end = min(offset + 7, distance)
                    start_point = (first[0] + (second[0] - first[0]) * offset / distance, first[1] + (second[1] - first[1]) * offset / distance)
                    end_point = (first[0] + (second[0] - first[0]) * end / distance, first[1] + (second[1] - first[1]) * end / distance)
                    draw.line([position(start_point), position(end_point)], fill="#52657d", width=4)
                    offset += 12
            else:
                draw.line([position(first), position(second)], fill="#52657d", width=4)
        if edge["style"] != "lifeline":
            first, second = points[-2:]
            angle = math.atan2(second[1] - first[1], second[0] - first[0])
            arrow = [second, (second[0] - 10 * math.cos(angle) + 5 * math.sin(angle), second[1] - 10 * math.sin(angle) - 5 * math.cos(angle)), (second[0] - 10 * math.cos(angle) - 5 * math.sin(angle), second[1] - 10 * math.sin(angle) + 5 * math.cos(angle))]
            draw.polygon([position(point) for point in arrow], fill="#52657d")
        if edge.get("label"):
            size = label_size(diagram, edge)
            label_font = ImageFont.truetype(font_path, round(size * scale))
            center = position((edge["label_x"], edge["label_y"]))
            box = draw.textbbox(center, edge["label"], font=label_font, anchor="ms")
            draw.rectangle((box[0] - 5, box[1] - 3, box[2] + 5, box[3] + 3), fill="white")
            draw.text(center, edge["label"], font=label_font, fill="#39475c", anchor="ms")
    for node in diagram["nodes"]:
        if node["shape"] != "group":
            vertex(node)
    image.save(destination, dpi=(300, 300))
    return font_path

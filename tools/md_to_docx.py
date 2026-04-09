import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

NS_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def xml_escape(s: str) -> str:
    return (
        s.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&apos;')
    )


def para(text: str | None = None, style: str | None = None) -> str:
    if text is None or text == '':
        return '<w:p/>'

    t = xml_escape(text)
    ppr = ''
    if style:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>'

    # xml:space preserve prevents Word from collapsing multiple spaces
    return (
        '<w:p>'
        f'{ppr}'
        '<w:r>'
        '<w:t xml:space="preserve">'
        f'{t}'
        '</w:t>'
        '</w:r>'
        '</w:p>'
    )


def build_document_xml(lines: list[str]) -> str:
    parts: list[str] = []

    for raw in lines:
        line = raw.rstrip('\n')
        stripped = line.strip()

        if stripped == '---':
            parts.append(para(''))
            continue

        if stripped == '':
            parts.append(para(''))
            continue

        # Headings
        if stripped.startswith('#'):
            # Count leading #
            level = 0
            for ch in stripped:
                if ch == '#':
                    level += 1
                else:
                    break
            if level > 0 and stripped[level:level+1] == ' ':
                text = stripped[level+1:]
                style = {1: 'Heading1', 2: 'Heading2', 3: 'Heading3', 4: 'Heading4'}.get(level, 'Heading4')
                parts.append(para(text, style=style))
                continue

        # Bullets
        if stripped.startswith('- '):
            parts.append(para('• ' + stripped[2:]))
            continue

        parts.append(para(line))

    body = ''.join(parts)

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{NS_W}" xmlns:r="{NS_R}">'
        '<w:body>'
        f'{body}'
        '<w:sectPr>'
        '<w:pgSz w:w="12240" w:h="15840"/>'  # A4 portrait-ish in twips
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
        '</w:sectPr>'
        '</w:body>'
        '</w:document>'
    )


def build_styles_xml() -> str:
    # Minimal styles so Heading1..4 render as headings in Word reliably.
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{NS_W}">' 
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/>'
        '</w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1">'
        '<w:name w:val="heading 1"/>'
        '<w:basedOn w:val="Normal"/>'
        '<w:uiPriority w:val="9"/>'
        '<w:qFormat/>'
        '<w:pPr><w:outlineLvl w:val="0"/></w:pPr>'
        '</w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading2">'
        '<w:name w:val="heading 2"/>'
        '<w:basedOn w:val="Normal"/>'
        '<w:uiPriority w:val="9"/>'
        '<w:qFormat/>'
        '<w:pPr><w:outlineLvl w:val="1"/></w:pPr>'
        '</w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading3">'
        '<w:name w:val="heading 3"/>'
        '<w:basedOn w:val="Normal"/>'
        '<w:uiPriority w:val="9"/>'
        '<w:qFormat/>'
        '<w:pPr><w:outlineLvl w:val="2"/></w:pPr>'
        '</w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading4">'
        '<w:name w:val="heading 4"/>'
        '<w:basedOn w:val="Normal"/>'
        '<w:uiPriority w:val="9"/>'
        '<w:qFormat/>'
        '<w:pPr><w:outlineLvl w:val="3"/></w:pPr>'
        '</w:style>'
        '</w:styles>'
    )


def build_content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '</Types>'
    )


def build_root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        '</Relationships>'
    )


def build_document_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    )


def build_core_xml(title: str) -> str:
    # Use UTC timestamps for doc props.
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f'<dc:title>{xml_escape(title)}</dc:title>'
        '<dc:creator>Codex CLI</dc:creator>'
        '<cp:lastModifiedBy>Codex CLI</cp:lastModifiedBy>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
        '</cp:coreProperties>'
    )


def build_app_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>Codex CLI</Application>'
        '</Properties>'
    )


def main() -> int:
    if len(sys.argv) != 3:
        print('Usage: md_to_docx.py <input.md> <output.docx>')
        return 2

    md_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    if not md_path.exists():
        print(f'Input not found: {md_path}')
        return 1

    lines = md_path.read_text(encoding='utf-8').splitlines(True)

    doc_xml = build_document_xml(lines)
    styles_xml = build_styles_xml()

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', build_content_types_xml())
        z.writestr('_rels/.rels', build_root_rels_xml())
        z.writestr('docProps/core.xml', build_core_xml(title=md_path.stem))
        z.writestr('docProps/app.xml', build_app_xml())
        z.writestr('word/document.xml', doc_xml)
        z.writestr('word/styles.xml', styles_xml)
        z.writestr('word/_rels/document.xml.rels', build_document_rels_xml())

    print(f'Wrote: {out_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

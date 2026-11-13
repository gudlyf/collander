"""Regenerate fixtures/sample.enex (a tiny synthetic Evernote export).

Run from backend/:  uv run python tests/fixtures/make_sample_enex.py
"""

import base64
import hashlib
import io
from pathlib import Path

from PIL import Image

img = Image.new("RGB", (40, 30), (200, 80, 60))
buf = io.BytesIO()
img.save(buf, "PNG")
data = buf.getvalue()
h = hashlib.md5(data).hexdigest()
b64 = base64.b64encode(data).decode()

ENML = '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">'

enex = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE en-export SYSTEM "http://xml.evernote.com/pub/evernote-export4.dtd">
<en-export export-date="20240101T000000Z" application="Evernote" version="10">
  <note>
    <title>Grandma's Chili</title>
    <created>20190305T181500Z</created>
    <tag>Dinner</tag>
    <tag>Family Recipes</tag>
    <note-attributes><source-url>https://example.com/chili</source-url></note-attributes>
    <content><![CDATA[{ENML}
<en-note><div>A hearty chili for cold nights.</div><div><br/></div>
<div><b>Ingredients</b></div><ul><li>1 lb ground beef</li><li>1 onion, chopped</li>
<li>2 cans kidney beans</li><li>2 tbsp chili powder</li></ul>
<div><b>Directions</b></div><ol><li>Brown the beef with the onion.</li>
<li>Add beans and chili powder; simmer 30 minutes.</li></ol>
<en-media hash="{h}" type="image/png"/></en-note>]]></content>
    <resource>
      <data encoding="base64">{b64}</data>
      <mime>image/png</mime>
      <resource-attributes><file-name>chili.png</file-name></resource-attributes>
    </resource>
  </note>
  <note>
    <title>Recipe card scan</title>
    <created>20200101T120000Z</created>
    <content><![CDATA[{ENML}<en-note><en-media hash="{h}" type="image/png"/></en-note>]]></content>
    <resource><data encoding="base64">{b64}</data><mime>image/png</mime></resource>
  </note>
  <note>
    <title>Car insurance renewal</title>
    <created>20210101T120000Z</created>
    <content><![CDATA[{ENML}<en-note><div>Policy renews in March. Call the agent.</div>
<en-todo checked="true"/>Done</en-note>]]></content>
  </note>
</en-export>
"""

(Path(__file__).parent / "sample.enex").write_text(enex)

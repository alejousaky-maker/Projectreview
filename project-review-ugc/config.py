import os
from pathlib import Path
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env', override=False)
UPSTREAM = ROOT / 'vendor' / 'ugc-factory-core'
JOBS = ROOT / 'jobs'
OUTPUTS = ROOT / 'outputs'
for directory in (JOBS, OUTPUTS):
    directory.mkdir(exist_ok=True)
BRAND_RULES = """Project Review sells NFC Review Stickers, Small NFC Review Stands and Big NFC Review Stands.
The sticker is a rigid round adhesive disc with moderate thickness and adhesive on its back.
Never depict paper peeling or QR codes unless requested. NFC is the primary interaction.
One tap sends customers directly to their Google review page. Pay once, no subscription.
Focus on less friction, more reviews, trust and visibility without guaranteed results.
Natural phone-camera creator delivery, subtle gestures, blinking, pauses and skin texture.
Do not invent personal testimonials or imply the creator used the product.
"""
def persona_status(name='project_review'):
    import re
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', name):
        return {'status': 'persona incomplete', 'missing': ['invalid persona name']}
    directory = ROOT / 'personas' / name
    missing = [n for n in ('reference.jpg', 'reference.wav', 'persona.json', 'scene_bible.json')
               if not (directory / n).is_file() or (directory / n).stat().st_size == 0]
    return {'status': 'persona incomplete' if missing else 'ready', 'missing': missing}

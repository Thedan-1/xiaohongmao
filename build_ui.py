"""Compile the offline workbench from editable HTML/CSS/JS and pinned Motion."""
from pathlib import Path
import hashlib

ROOT=Path(__file__).resolve().parent

def build():
    motion=(ROOT/'vendor/motion-12.23.24.js').read_bytes()
    assert hashlib.sha256(motion).hexdigest()=='631dbfc6984d0078a6edbc9885a87d5d941ad9d7534740237c9679140c0dfdc5'
    html=(ROOT/'studio-ui.html').read_text(encoding='utf-8')
    css=(ROOT/'studio-design.css').read_text(encoding='utf-8')
    script='\n'.join((ROOT/name).read_text(encoding='utf-8') for name in ['studio-ui.js','settings-ui.js','updates-ui.js'])
    import release_config
    html=html.replace('__APP_VERSION__',release_config.load()['version'])
    html=html.replace('</style>',css+'\n</style>',1)
    html=html.replace('<!-- STUDIO_SCRIPT -->','<script>'+motion.decode('utf-8')+'</script>\n<script>'+script+'</script>')
    (ROOT/'ui.html').write_text(html,encoding='utf-8')

if __name__=='__main__':build()

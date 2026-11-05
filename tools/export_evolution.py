"""Export saved factor studies to a portable HTML snapshot, using stdlib only."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def export_files():
    studies = [json.loads(p.read_text()) for p in sorted((ROOT/'results/evolution_runs').glob('*/study.json'))]
    studies.sort(key=lambda x:x['created_at'], reverse=True)
    if not studies: return {}
    html = (ROOT/'web/dist/evolution.html').read_text()
    css = (ROOT/'web/dist/evolution.css').read_text()
    js = (ROOT/'web/dist/evolution.js').read_text()
    payload = json.dumps(studies, ensure_ascii=False, allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    html = html.replace('<link rel="stylesheet" href="/evolution.css">','<style>'+css+'</style>')
    html = html.replace('<script src="/evolution.js"></script>', '<script>window.SAVED_EVOLUTION='+payload+';</script><script>'+js+'</script>')
    result = {'evolution.html': html}
    archive = ROOT/'results/evolution_20261030/report.html'
    if archive.exists(): result['evolution-20261030.html'] = archive.read_text()
    return result


if __name__ == '__main__':
    for name, content in export_files().items():
        path = ROOT/'report_site'/name
        path.parent.mkdir(exist_ok=True)
        path.write_text(content)
        print(path.relative_to(ROOT))

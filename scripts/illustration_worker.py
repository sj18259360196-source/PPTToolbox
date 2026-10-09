"""Internal numerical worker, launched only after the manager's policy checks."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from project_journal import safe
def main():
 p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--request',required=True)
 a=p.parse_args();request=safe(a.project,a.request);body=json.loads(request.read_text('utf-8'))
 if body['operation'] not in ('fit_paths','compare_regions','selection_masks','freeze_evaluation','evaluate_stages','share_rings'):raise ValueError('Unknown numeric operation')
 if Path(body['args']['project']).resolve()!=a.project.resolve():raise ValueError('Worker project mismatch')
 from illustration_workflow import run_inline
 result=run_inline(a.project,body['operation'],body['args'])
 output=request.parent/'result.json'
 with output.open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,ensure_ascii=False,allow_nan=False)
if __name__=='__main__':main()

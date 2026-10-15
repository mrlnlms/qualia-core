"""Compara palavras contra CSV de referência, sem carregar modelos ou corrigir ASR."""
import argparse
import csv
from datetime import datetime,timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from qualia.transcription.comparison import align_words


def sha(path):
 return hashlib.sha256(path.read_bytes()).hexdigest()


def source(path):
 with path.open(encoding='utf-8-sig',newline='') as stream:
  reader=csv.DictReader(stream)
  if 'Text' not in (reader.fieldnames or []):raise ValueError('CSV sem coluna Text.')
  rows=list(reader)
 words=[]
 for index,row in enumerate(rows):
  for word in re.findall(r'\w+',row['Text']):
   words.append({'word':word,'normalized':word.casefold(),'row':index,'start':row.get('Start Time',''),'end':row.get('End Time','')})
 return words


def differences(operations,reference,generated):
 groups=[];current=[]
 for op in operations:
  if op[0]=='equal':
   if current:groups.append(current);current=[]
  else:current.append(op)
 if current:groups.append(current)
 rows=[]
 for group in groups:
  ref_indices=[i for kind,i,j in group if kind!='insert']
  gen_indices=[j for kind,i,j in group if kind!='delete']
  ri=min(group[0][1],len(reference)-1);gi=min(group[0][2],len(generated)-1)
  def span(words,indices,fallback):
   if not words:return ('','','','')
   left=min(indices) if indices else max(0,fallback);right=max(indices)+1 if indices else left
   return (' '.join(w['word'] for w in words[left:right]),words[left]['start'],words[max(left,right-1)]['end'],
           ' '.join(w['word'] for w in words[max(0,left-6):min(len(words),max(right,left+1)+6)]))
  rt,rs,re_,rc=span(reference,ref_indices,ri);gt,gs,ge,gc=span(generated,gen_indices,gi)
  rows.append({'difference':len(rows)+1,'operations':','.join(dict.fromkeys(op[0] for op in group)),
               'reference_text':rt,'generated_text':gt,'reference_start':rs,'reference_end':re_,
               'generated_start':gs,'generated_end':ge,'reference_context':rc,'generated_context':gc})
 return rows


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 try:os.nice(15)
 except (AttributeError,OSError):pass
 if args.output.exists():raise ValueError('Saída já existe; usar outra versão.')
 config=json.loads(args.manifest.read_text());root=args.manifest.resolve().parent;run=root/config['output']
 args.output.mkdir(parents=True)
 reports=[]
 for case in config['inputs']:
  if not case.get('reference'):continue
  ref=root/case['reference'];gen=run/f"{case['id']}.csv"
  rw=source(ref);gw=source(gen)
  aligned=align_words([w['normalized'] for w in rw],[w['normalized'] for w in gw]);ops=aligned.pop('operations')
  assert aligned['equal']+aligned['substitute']+aligned['delete']==len(rw)
  assert aligned['equal']+aligned['substitute']+aligned['insert']==len(gw)
  diffs=differences(ops,rw,gw)
  report={'id':case['id'],'reference':str(ref.resolve()),'reference_sha256':sha(ref),'generated':str(gen.resolve()),'generated_sha256':sha(gen),**aligned,'difference_blocks':len(diffs)}
  reports.append(report)
  (args.output/f"{case['id']}.differences.json").write_text(json.dumps(diffs,ensure_ascii=False,indent=2)+'\n')
  with (args.output/f"{case['id']}.differences.csv").open('w',newline='',encoding='utf-8') as stream:
   fields=['difference','operations','reference_start','reference_end','generated_start','generated_end','reference_text','generated_text','reference_context','generated_context']
   writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(diffs)
  body=['<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Diferenças de texto</title><style>body{font:16px/1.6 system-ui;margin:35px;max-width:1200px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:12px;vertical-align:top}small{color:#555}</style>',f"<h1>{html.escape(case['id'])}: Dovetail × Qualia</h1>",'<p>Diferenças de palavras, ignorando maiúsculas e pontuação. A referência pode conter erros. Tempos identificam blocos do CSV, não precisão por palavra. Contexto ajuda a localizar a diferença; o texto original não foi modificado.</p><table><tr><th>Dovetail</th><th>Qualia</th></tr>']
  for d in diffs:
   body.append('<tr>'+''.join(f"<td><small>{html.escape(d[prefix+'_start'])} · diferença {d['difference']}</small><p><strong>{html.escape(d[prefix+'_text']) or '—'}</strong></p><p>{html.escape(d[prefix+'_context'])}</p></td>" for prefix in ['reference','generated'])+'</tr>')
  body.append('</table></html>');(args.output/f"{case['id']}.html").write_text('\n'.join(body))
  print(json.dumps(report,ensure_ascii=False),flush=True)
 summary={'created_utc':datetime.now(timezone.utc).isoformat(),'manifest_sha256':sha(args.manifest),
          'normalization':'Unicode word tokens, casefold; pontuação/caixa ignoradas; acentos, números e palavras de preenchimento preservados.',
          'method':'Levenshtein mínimo exato por palavra: WER=(substituições+exclusões+inserções)/palavras de referência. Empates priorizam substituição, exclusão, inserção.',
          'warning':'Divergência relativa ao Dovetail; não mede verdade do áudio, qualidade semântica ou atribuição de falantes. Não interpretar 1-WER como acurácia validada.',
          'model_execution':False,'references_used_only_for_comparison':True,
          'code':{str(p.relative_to(REPO)):sha(p) for p in [Path(__file__),REPO/'qualia/transcription/comparison.py']},'cases':reports}
 (args.output/'comparison.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 lines=['# Comparação textual — Dovetail × Qualia v4','',summary['warning'],'',
        '| Amostra | Palavras Dovetail | Palavras Qualia | Substituições | Ausentes em relação ao Dovetail | Extras em relação ao Dovetail | Divergência WER |','|---|---:|---:|---:|---:|---:|---:|']
 for r in reports:lines.append(f"| [{r['id']}]({r['id']}.html) | {r['reference_words']} | {r['generated_words']} | {r['substitute']} | {r['delete']} | {r['insert']} | {r['wer']:.1%} |")
 lines+=['','Normalização: '+summary['normalization'],'','Método: '+summary['method'],'',
         'A comparação anterior era de concordância temporal dos falantes. Esta avaliação lexical é separada: preserva a ordem das palavras e ignora diferenças de segmentação dos CSVs. Não usa o texto Dovetail para gerar/corrigir o Qualia.','',
         'Cada link abre os blocos divergentes lado a lado com contexto e tempos dos blocos de origem. Os CSV/JSON correspondentes preservam todas as diferenças; exclusão significa ausência relativa à referência, e não prova de fala perdida. Há variações de redação, abreviações e transcrição de nomes que contam como diferenças mesmo quando o sentido é parecido. Não houve escuta humana integral nem execução de modelos nesta comparação.']
 (args.output/'README.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()

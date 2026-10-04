import json
from datasets import load_dataset
ds=load_dataset("McGill-NLP/WebLINX","reranking",split="test_iid")
print("N",len(ds))
print("FEATURES",ds.features)
for i in range(min(3,len(ds))):
    x=ds[i]
    print("ROW",i,"KEYS",list(x))
    for k,v in x.items():
        if isinstance(v,list):
            print(k,"LEN",len(v),"FIRST",repr(v[:2])[:1500])
        else:
            print(k,repr(v)[:1000])

from huggingface_hub import hf_hub_download, HfApi
api=HfApi(); raw_sha=api.dataset_info("McGill-NLP/WebLINX-full").sha
p=hf_hub_download("McGill-NLP/WebLINX-full","candidates/test_iid.jsonl",repo_type="dataset",revision=raw_sha)
import os
print("CAND_FILE",p,"BYTES",os.path.getsize(p),"SHA",raw_sha)
with open(p,"r",encoding="utf-8") as h:
    for i in range(2):
        z=json.loads(next(h))
        print("CAND_ROW",i,"KEYS",list(z),"SAMPLE",repr(z)[:2500])

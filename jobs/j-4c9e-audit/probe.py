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

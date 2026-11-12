"""CLIP encoding with phrase boundaries and actual embedding emphasis."""
import re


def pack_prompt(tokenizer, segments, with_regions=False):
    capacity=tokenizer.model_max_length-2
    blocks=[]
    tokens=[]
    weights=[]
    regions=[]
    for segment in segments:
        # Split exceptionally long sentences only at punctuation, never through
        # a color/garment pair. A phrase that cannot fit must be shortened.
        pieces=[segment['text']]
        if len(tokenizer(pieces[0],add_special_tokens=False).input_ids)>capacity:
            pieces=[p.strip() for p in re.split(r'[;,，；.]',pieces[0]) if p.strip()]
        for piece in pieces:
            ids=tokenizer(piece+'.',add_special_tokens=False).input_ids
            if len(ids)>capacity:
                raise ValueError('有一段描述太长，无法完整理解。请拆成较短的句子：'+piece[:70])
            if tokens and len(tokens)+len(ids)>capacity:
                blocks.append((tokens,weights,regions) if with_regions else (tokens,weights));tokens=[];weights=[];regions=[]
            tokens.extend(ids);weights.extend([segment.get('weight',1.0)]*len(ids));regions.extend([segment.get('region','global')]*len(ids))
    if tokens:blocks.append((tokens,weights,regions) if with_regions else (tokens,weights))
    if len(blocks)>6:
        raise ValueError('人物细节过多，请精简后重试；本次没有截断描述或开始绘制。')
    return blocks or [([],[],[]) if with_regions else ([],[])]


def encode_plan(pipe, plan):
    import torch
    tokenizer=pipe.tokenizer
    positive=pack_prompt(tokenizer,plan['segments'],with_regions=True)
    negative=pack_prompt(tokenizer,[dict(text=word.strip(),weight=1.0) for word in plan['negative_prompt'].split(',') if word.strip()],with_regions=True)
    count=max(len(positive),len(negative))
    outputs=[]
    all_regions=[]
    with torch.inference_mode():
        for blocks in (positive,negative):
            chunks=[]
            for index in range(count):
                tokens,weights,regions=blocks[index] if index<len(blocks) else ([],[],[])
                ids=[tokenizer.bos_token_id]+tokens+[tokenizer.eos_token_id]
                emphasis=[1.0]+weights+[1.0]
                padding=tokenizer.model_max_length-len(ids)
                if blocks is positive:all_regions.extend(['global']+regions+[regions[-1] if regions else 'global']*(padding+1))
                ids += [tokenizer.pad_token_id]*padding;emphasis += [1.0]*padding
                encoded=pipe.text_encoder(torch.tensor([ids],device=pipe._execution_device))[0]
                # Weights act on contextual embeddings, not literal '(x:1.2)'
                # text that the native Diffusers pipeline does not interpret.
                scale=torch.tensor(emphasis,device=encoded.device,dtype=encoded.dtype)[None,:,None]
                original=encoded.float().square().mean().sqrt()
                encoded=encoded*scale
                encoded=encoded*(original/encoded.float().square().mean().sqrt().clamp_min(1e-6)).to(encoded.dtype)
                chunks.append(encoded)
            outputs.append(torch.cat(chunks,dim=1))
    return outputs,dict(blocks=count,positive_tokens=sum(len(t) for t,_,_ in positive),
                        negative_tokens=sum(len(t) for t,_,_ in negative),truncated=False,token_regions=all_regions)

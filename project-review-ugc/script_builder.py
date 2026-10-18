import json
import re
import os
import httpx
from config import BRAND_RULES

def build_script(topic, audience='local business owners', business_type='general local business',
                 tone='casual', duration=25, cta_style='try one tap', style='educational', frames=121):
    limit = min(12, int(frames / 24 * 2.5))
    prompt = dict(topic=topic, audience=audience, business_type=business_type, tone=tone,
                  duration=duration, cta_style=cta_style, style=style)
    clean_topic = re.sub(r'https?://\S+|www\.\S+|\b\S+\.(?:com|net|org)\b', '', topic, flags=re.I)
    clean_topic = re.sub(r'link in bio', 'one tap', clean_topic, flags=re.I)
    topic_words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", clean_topic)[:max(3, limit-3)]
    hook = 'Let us talk ' + ' '.join(topic_words) if topic_words else 'Let us make leaving a Google review feel easier'
    phases = [
        ('Hook', hook),
        ('Problem', 'Happy customers often leave before anyone asks for a review'),
        ('Explanation', 'Every extra step makes sharing their experience feel like work'),
        ('Solution', 'Project Review takes them straight to your Google review page'),
        ('Solution', 'One NFC tap means less friction and more visible trust'),
        ('CTA', 'Try one tap and make your next review easier'),
        ('CTA', 'Pay once and keep using it without a subscription')]
    # Budget at natural two words per second; final duration depends on model speech.
    budget = round(duration * 2)
    chosen=[]; count=0
    for label,line in phases:
        if count + len(line.split()) <= budget or len(chosen)<2:
            chosen.append((label,line)); count+=len(line.split())
    if not any(label=='CTA' for label,_ in chosen):
        chosen[-1]=phases[-2]
    source='deterministic'
    if os.getenv('UGC_LLM_API_URL') and os.getenv('UGC_LLM_MODEL'):
        try:
            response=httpx.post(os.environ['UGC_LLM_API_URL'], timeout=60,
                headers={'Authorization': 'Bearer '+os.getenv('UGC_LLM_API_KEY','')},
                json={'model':os.environ['UGC_LLM_MODEL'], 'messages':[
                  {'role':'system','content':BRAND_RULES+f' Return only a JSON list of spoken strings, each five to {limit} words, one sentence, no URLs or link in bio. Use Hook, Problem, Explanation, Solution, CTA. Target two words per second.'},
                  {'role':'user','content':json.dumps(prompt)}]})
            response.raise_for_status()
            lines=json.loads(response.json()['choices'][0]['message']['content'])
            if not isinstance(lines,list) or not lines or not all(isinstance(x,str) and 1<=len(x.split())<=limit and not re.search(r'https?://|www\.|link in bio|\w+\.com',x,re.I) for x in lines):
                raise ValueError('Invalid LLM script')
            chosen=[('Spoken',x) for x in lines];source='llm'
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            source='deterministic (LLM unavailable or invalid)'
    segments=[]
    for _,line in chosen:
        words=re.sub(r'[.!?]','',line).split()
        segments.extend(' '.join(words[i:i+limit]) for i in range(0,len(words),limit))
    return {'topic':topic,'brief':prompt,'source':source,'outline':dict((k,v) for k,v in phases),
            'segments':segments,'estimated_seconds':round(sum(len(s.split()) for s in segments)/2,1)}

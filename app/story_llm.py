"""Local writing model using the same guarded lifecycle as translation."""
import json
import secrets
from settings import WRITING_LLM
from local_model_runtime import LocalModelSession


class StoryModel(LocalModelSession):
    def __init__(self, folder, cancelled, thinking=True, vision=False):
        self.folder, self.cancelled = folder, cancelled
        self.thinking, self.vision = thinking, vision
        super().__init__(folder/'writing-model.log', self._cancel)

    def _cancel(self):
        if self.cancelled():
            raise InterruptedError('已停止写作，完成的段落已保存，可继续。')

    def __enter__(self):
        from director_plan import policy
        cpu = self.vision and policy().get('vision_device', 'cpu') == 'cpu'
        args = ['--reasoning', 'on' if self.thinking else 'off',
                '--reasoning-format', 'deepseek', '--reasoning-budget', '1024' if self.thinking else '0']
        if self.vision:
            projector = WRITING_LLM.parent/'mmproj-F16.gguf'
            if not projector.is_file():
                raise ValueError('缺少本地画面检查组件。')
            args += ['--mmproj', str(projector)]
            if cpu:
                args += ['--no-mmproj-offload']
        return self.start(WRITING_LLM, args, cpu=cpu)

    def request(self, instructions, context, schema, tokens=3000):
        payload = dict(messages=[dict(role='system', content=instructions),
            dict(role='user', content=json.dumps(context, ensure_ascii=False))],
            temperature=.35, top_p=.8, top_k=20, min_p=0., presence_penalty=0.,
            seed=secrets.randbelow(2**31), repeat_penalty=1., max_tokens=tokens+(1024 if self.thinking else 0), stream=False,
            chat_template_kwargs={'enable_thinking': self.thinking},
            response_format=dict(type='json_schema', json_schema=dict(name='story', strict=True, schema=schema)))
        result = self.complete(payload)
        with (self.folder/'model-usage.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps({**result.get('usage', {}), 'model': WRITING_LLM.name, 'thinking': self.thinking})+'\n')
        choice = result['choices'][0]
        if choice.get('finish_reason') == 'length':
            raise ValueError('模型输出达到长度上限，本段未写入；可点击继续重新生成本段。')
        try:
            return json.loads(choice['message']['content'])
        except (ValueError, TypeError):
            raise ValueError('本地模型没有返回完整的剧本格式，本段未写入。')

    def __exit__(self, exc_type, exc, traceback):
        self.close(exc)

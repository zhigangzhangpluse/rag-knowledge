"""会话按知识库隔离；保存成功完成的问答轮次。"""
import json
import threading
import time


class RedisSessions:
    def __init__(self, settings):
        from redis import Redis
        self.client = Redis.from_url(settings.redis_url, decode_responses=True,
                                     socket_connect_timeout=5, socket_timeout=5)
        self.ttl = settings.session_ttl

    def key(self, kb_id, session_id):
        return f"rag:session:{kb_id}:{session_id}"

    def get(self, kb_id, session_id):
        rows = self.client.lrange(self.key(kb_id, session_id), -12, -1)
        return [json.loads(row) for row in rows]

    def append(self, kb_id, session_id, question, answer):
        key = self.key(kb_id, session_id)
        with self.client.pipeline(transaction=True) as pipe:
            pipe.rpush(key, json.dumps({"role": "user", "content": question}, ensure_ascii=False),
                       json.dumps({"role": "assistant", "content": answer}, ensure_ascii=False))
            pipe.ltrim(key, -12, -1)
            pipe.expire(key, self.ttl)
            pipe.execute()

    def clear(self, kb_id, session_id):
        self.client.delete(self.key(kb_id, session_id))

    def health(self):
        self.client.ping()


class MemorySessions:
    def __init__(self, settings):
        self.ttl, self.rows, self.lock = settings.session_ttl, {}, threading.Lock()

    def get(self, kb_id, session_id):
        with self.lock:
            expiry, rows = self.rows.get((kb_id, session_id), (0, []))
            return list(rows) if expiry > time.time() else []

    def append(self, kb_id, session_id, question, answer):
        rows = self.get(kb_id, session_id)
        rows += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        with self.lock:
            self.rows[(kb_id, session_id)] = (time.time() + self.ttl, rows[-12:])

    def clear(self, kb_id, session_id):
        with self.lock:
            self.rows.pop((kb_id, session_id), None)

    def health(self):
        return None

# ----------------------------------------------------------------------
# 阅读入口：管理知识库内的对话历史，支持 Redis 生产实现和内存演示实现。
# Redis key 同时包含 kb_id 与 session_id，防止不同知识库的同名会话串历史。pipeline 事务把追加、截断和过期放在一起。会话保留最近 12 条消息，即 6 轮完整问答。
# ----------------------------------------------------------------------
import json
import threading
import time


# ----------------------------------------------------------------------
# Redis 这里只保存聊天历史，不是存文档向量，也不负责判断知识库版本。
# key 同时含 kb_id 和 session_id，避免同一会话 ID 在不同知识库串历史。
# 最多保留 12 条消息，正常一问一答两条，约为最近 6 轮；不是无限记忆。
# TTL 是闲置过期时间，append 会续期；它和 Redis 是否配置磁盘持久化是两回事。
# 代码示例：sessions.get(kb_id, session_id) 读历史，sessions.append(...) 保存完整一轮。
# 面试问：为何用 Redis？答：低延迟读取、列表操作和过期机制方便；代价是增加一个外部服务。
# transaction=True 将写入、裁剪、续期一起执行，但不等于 SQL 那样支持执行错误后的自动回滚。
# 同一会话并发发问仍可能乱序；此处事务没有锁住整次模型生成。
# ----------------------------------------------------------------------
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

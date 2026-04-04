// @version: 1
// @creates: EntryPoint:XxlJob, EntryPoint:MQConsumer, Spring:FeignClient
// @description: 自定义注解识别 (@XxlJob, @RocketMQ, @Feign)

// ========================================
// Step 5: 自定义注解与框架集成
// 识别 @XxlJob, @RocketMQMessageListener, @FeignClient 等入口
// 建立 MQ producer→consumer 路由
// ========================================

// --- 5a: 标记 @XxlJob 入口方法 ---
// @XxlJob 注解的方法是定时任务入口
MATCH (m:Method)-[:ANNOTATED_BY]->(ann)-[:OF_TYPE]->(annType:Type)
WHERE annType.fqn = 'com.xxl.job.core.handler.annotation.XxlJob'
SET m:EntryPoint:XxlJob
RETURN count(m) AS xxljob_entries;

// --- 5b: 标记 @Scheduled 入口方法 ---
MATCH (m:Method)-[:ANNOTATED_BY]->(ann)-[:OF_TYPE]->(annType:Type)
WHERE annType.fqn = 'org.springframework.scheduling.annotation.Scheduled'
SET m:EntryPoint:Scheduled
RETURN count(m) AS scheduled_entries;

// --- 5c: 标记 API 入口方法（@GetMapping/@PostMapping 等）---
MATCH (m:Method)-[:ANNOTATED_BY]->(ann)-[:OF_TYPE]->(annType:Type)
WHERE annType.fqn IN [
    'org.springframework.web.bind.annotation.GetMapping',
    'org.springframework.web.bind.annotation.PostMapping',
    'org.springframework.web.bind.annotation.PutMapping',
    'org.springframework.web.bind.annotation.DeleteMapping',
    'org.springframework.web.bind.annotation.PatchMapping',
    'org.springframework.web.bind.annotation.RequestMapping'
]
SET m:EntryPoint:ApiEndpoint
RETURN count(m) AS api_entries;

// --- 5d: 标记 RocketMQ 消费者类 ---
// @RocketMQMessageListener 标注在类上，类中的 onMessage 方法是消费入口
MATCH (cls:Java:Type)-[:ANNOTATED_BY]->(ann)-[:OF_TYPE]->(annType:Type)
WHERE annType.fqn = 'org.apache.rocketmq.spring.annotation.RocketMQMessageListener'
SET cls:MQ:Consumer
WITH cls
OPTIONAL MATCH (cls)-[:DECLARES]->(m:Method)
WHERE m.name IN ['onMessage', 'handleMessage']
SET m:EntryPoint:MQConsumer
RETURN count(cls) AS mq_consumers;

// --- 5e: 标记 @FeignClient 接口 ---
// Feign 接口的方法调用实际是 HTTP 远程调用
MATCH (cls:Java:Type)-[:ANNOTATED_BY]->(ann)-[:OF_TYPE]->(annType:Type)
WHERE annType.fqn = 'org.springframework.cloud.openfeign.FeignClient'
SET cls:Spring:FeignClient
RETURN count(cls) AS feign_clients;

// --- 5f: MQ PRODUCES_MESSAGE / CONSUMES_MESSAGE 路由 ---
// 通过 topic 名称关联 MQ 生产者和消费者
// 生产者: 调用 RocketMQTemplate.send/syncSend/asyncSend/convertAndSend 的方法
MATCH (callerMethod:Method)-[:INVOKES]->(sendMethod:Method)
WHERE sendMethod.name IN ['send', 'syncSend', 'asyncSend', 'convertAndSend', 'sendOneWay']
MATCH (sendMethod)<-[:DECLARES]-(templateType:Java:Type)
WHERE templateType.fqn CONTAINS 'RocketMQTemplate'
   OR templateType.fqn CONTAINS 'MQProducer'
   OR templateType.fqn CONTAINS 'DefaultMQProducer'
SET callerMethod:MQ:Producer
RETURN count(DISTINCT callerMethod) AS mq_producers;

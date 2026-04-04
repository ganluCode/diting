// @version: 2
// @depends: 01-inheritance
// @creates: INJECTS, PRODUCES_BEAN, PUBLISHES_EVENT, HANDLES_EVENT, EVENT_ROUTES_TO
// @description: Spring DI 注入解析 + Event 路由

// ========================================
// Step 3: Spring DI 注入解析
// 建立 INJECTS 和 PRODUCES_BEAN 关系
// ========================================

// --- 3a: 标记注入点 ---
// 确保 @Autowired/@Inject 字段被标记为 Spring:InjectionPoint
MATCH (field:Field)-[:ANNOTATED_BY]->()-[:OF_TYPE]->(annotationType:Type)
WHERE annotationType.fqn IN [
    'org.springframework.beans.factory.annotation.Autowired',
    'jakarta.inject.Inject',
    'jakarta.annotation.Resource',
    'javax.inject.Inject',
    'javax.annotation.Resource'
]
  AND NOT field:Spring:InjectionPoint
SET field:Spring:InjectionPoint
RETURN count(field) AS injection_points_labeled;

// --- 3b: INJECTS ---
// 解析 @Autowired 字段: 找到字段类型的具体 Injectable 实现类
// 例如: OrderServiceImpl --INJECTS {field:'orderService'}--> OrderController
MATCH (ownerType:Java:Type)-[:DECLARES]->(field:Field:Spring:InjectionPoint),
      (field)-[:OF_TYPE]->(fieldType:Java:Type),
      (concreteType:Spring:Injectable)-[:IMPLEMENTS|EXTENDS*0..]->(fieldType)
WHERE concreteType:Class
  AND concreteType.abstract IS NULL
MERGE (concreteType)-[:INJECTS {field: field.name}]->(ownerType)
RETURN count(*) AS injections_resolved;

// --- 3c: PRODUCES_BEAN ---
// 解析 @Bean 方法: 配置类通过 @Bean 方法产出的 Bean 类型
MATCH (configType:Java:Type)-[:DECLARES]->(beanMethod:Method:Spring:BeanProducer),
      (beanMethod)-[:RETURNS]->(beanType:Java:Type)
WHERE beanType.fqn <> 'void'
MERGE (configType)-[:PRODUCES_BEAN {method: beanMethod.name}]->(beanType)
RETURN count(*) AS beans_resolved;

// ========================================
// Step 3d-3e: Spring Events 路由解析
// 建立 PUBLISHES_EVENT / HANDLES_EVENT / EVENT_ROUTES_TO 关系
//
// 覆盖场景：
//   ApplicationEventPublisher.publishEvent(event)
//   ApplicationEventPublisher.publishEvent(Object source)
//   ApplicationContext.publishEvent(event)
//   @EventListener(MyEvent.class) / 参数类型推断
//   @TransactionalEventListener
// ========================================

// --- 3d-1: 标记事件监听方法 ---
// @EventListener / @TransactionalEventListener 注解的方法 → :Spring:EventHandler
MATCH (listenerMethod:Method)-[:ANNOTATED_BY]->()-[:OF_TYPE]->(ann:Type)
WHERE ann.fqn IN [
    'org.springframework.context.event.EventListener',
    'org.springframework.transaction.event.TransactionalEventListener'
]
  AND NOT listenerMethod:Spring:EventHandler
SET listenerMethod:Spring:EventHandler
RETURN count(listenerMethod) AS event_handlers_labeled;

// --- 3d-2: HANDLES_EVENT（通过方法参数类型推断监听事件类型）---
// @EventListener 方法通常第一个参数就是事件类型
// jQAssistant 将参数建模为 Parameter 节点，通过 OF_TYPE 指向参数类型
MATCH (listenerMethod:Method:Spring:EventHandler)-[:HAS]->(param:Parameter),
      (param)-[:OF_TYPE]->(eventType:Java:Type)
WHERE param.index = 0
  AND eventType.fqn <> 'java.lang.Object'
  AND NOT (listenerMethod)-[:HANDLES_EVENT]->(eventType)
MERGE (listenerMethod)-[:HANDLES_EVENT]->(eventType)
RETURN count(*) AS handles_event_created;

// --- 3d-3: PUBLISHES_EVENT（publishEvent 调用者 → 事件类型）---
// 识别 caller -> publishEvent(new XxxEvent(...)) 中传入的参数类型
// 简化方案：在调用 publishEvent 的方法体内，找同一方法内 new 出的 ApplicationEvent 子类
MATCH (callerMethod:Method)-[:INVOKES]->(pubMethod:Method)
WHERE pubMethod.name IN ['publishEvent', 'multicastEvent', 'publish']
  AND (pubMethod.signature CONTAINS 'ApplicationEvent'
       OR pubMethod.signature CONTAINS 'Object')
MATCH (callerMethod)-[:INVOKES]->(ctor:Method)<-[:DECLARES]-(eventType:Java:Type)
WHERE ctor.name = '<init>'
  AND EXISTS {
      MATCH (eventType)-[:EXTENDS|IMPLEMENTS*0..]->(baseEvent:Java:Type)
      WHERE baseEvent.fqn IN [
          'org.springframework.context.ApplicationEvent',
          'org.springframework.context.PayloadApplicationEvent',
          'java.util.EventObject'
      ]
  }
MERGE (callerMethod)-[:PUBLISHES_EVENT]->(eventType)
RETURN count(*) AS publishes_event_created;

// --- 3d-4: PUBLISHES_EVENT 补充（POJO 事件，不继承 ApplicationEvent）---
// Spring 4.2+ 支持任意 POJO 作为事件，无需继承 ApplicationEvent
// 通过参数类型匹配：publishEvent 的参数如果是业务包内的类，也视为事件
MATCH (callerMethod:Method)-[:INVOKES]->(pubMethod:Method)
WHERE pubMethod.name IN ['publishEvent', 'multicastEvent', 'publish']
MATCH (callerMethod)-[:INVOKES]->(ctor:Method)<-[:DECLARES]-(eventType:Java:Type)
WHERE ctor.name = '<init>'
  AND NOT EXISTS {
      MATCH (eventType)-[:EXTENDS|IMPLEMENTS*0..]->(baseEvent:Java:Type)
      WHERE baseEvent.fqn IN [
          'org.springframework.context.ApplicationEvent',
          'org.springframework.context.PayloadApplicationEvent',
          'java.util.EventObject'
      ]
  }
  AND NOT (callerMethod)-[:PUBLISHES_EVENT]->(eventType)
  // 只取业务包内的类（避免误匹配 JDK/Spring 内部类）
  AND any(prefix IN ['com.', 'org.', 'net.', 'io.']
          WHERE eventType.fqn STARTS WITH prefix
          AND NOT eventType.fqn STARTS WITH 'org.springframework'
          AND NOT eventType.fqn STARTS WITH 'org.apache'
          AND NOT eventType.fqn STARTS WITH 'io.netty')
MERGE (callerMethod)-[:PUBLISHES_EVENT {inferred: true}]->(eventType)
RETURN count(*) AS pojo_events_created;

// --- 3e: EVENT_ROUTES_TO（publisher方法 → listener方法）---
// 通过共享的事件类型，将 PUBLISHES_EVENT 和 HANDLES_EVENT 串联
MATCH (publisher:Method)-[:PUBLISHES_EVENT]->(eventType:Java:Type)<-[:HANDLES_EVENT]-(listener:Method)
MERGE (publisher)-[:EVENT_ROUTES_TO {eventType: eventType.fqn}]->(listener)
RETURN count(*) AS event_routes_created;

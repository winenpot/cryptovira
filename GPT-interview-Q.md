Below is a recruiter-oriented question bank designed to distinguish a genuinely experienced Django/backend engineer from someone who mainly knows framework syntax. The questions progress from solid mid-level fundamentals toward senior-level architecture, distributed systems, production reliability, and blockchain-specific backend work.

## 1. Python — 10 questions

1. What is the difference between a shallow copy and a deep copy in Python, and where can using `copy.deepcopy()` become problematic?

2. Explain Python's GIL. What does it actually prevent, and why can a Python application still benefit from multiple threads?

3. When would you choose `asyncio` over multiprocessing or threading in a backend service?

4. What happens internally when Python executes a generator function? When are generators preferable to returning a list?

5. Explain Python's descriptor protocol and how `@property` is related to it.

6. What are mutable default arguments, and why is this code dangerous?

   ```python
   def add_item(item, items=[]):
       items.append(item)
       return items
   ```

7. Explain the difference between an iterator, iterable, generator, and generator expression.

8. How does Python's garbage collector work in addition to reference counting?

9. What are the practical performance implications of using lists, tuples, sets, and dictionaries for large datasets?

10. You discover that a Django worker's memory usage continuously grows over several hours. How would you investigate whether this is a Python memory leak, application-level retention, or normal allocator behavior?

---

# 2. Django fundamentals and architecture — 15 questions

11. Explain Django's request/response lifecycle from the moment a request reaches the server until the response is returned.

12. What is the difference between Django middleware and DRF permissions/authentication? Where should each type of logic live?

13. What problems can arise from putting business logic directly inside Django views?

14. How would you structure a large Django project containing dozens of domains while avoiding a giant `models.py`, `views.py`, or `utils.py`?

15. What are Django signals? Why are they often considered dangerous for important business logic?

16. What is the difference between overriding `Model.save()` and using a service layer for business operations?

17. How does Django's ORM translate a QuerySet into SQL?

18. Explain lazy evaluation in Django QuerySets. What operations trigger database evaluation?

19. What happens when you iterate over the same QuerySet multiple times?

20. What is the difference between `select_related()` and `prefetch_related()`? Give an example where using the wrong one significantly hurts performance.

21. What is the N+1 query problem? How would you detect and eliminate it in Django?

22. How would you implement soft deletion in Django? What problems can it introduce?

23. How would you design Django models for an application where historical records must never be modified or deleted?

24. What are Django migrations actually doing? How would you safely deploy a migration that adds a non-nullable column to a table containing hundreds of millions of rows?

25. How would you organize configuration and secrets across local development, staging, and production environments?

---

# 3. Django REST Framework — 15 questions

26. Explain the lifecycle of a DRF request through authentication, permissions, throttling, parsing, serializer validation, view execution, and response rendering.

27. What is the difference between authentication and authorization in DRF?

28. When would you use `APIView`, `GenericAPIView`, `ViewSet`, and `ModelViewSet`?

29. What problems can arise from using `ModelViewSet` everywhere?

30. How would you design an API endpoint that processes a financial transaction and must never execute the transaction twice?

31. How would you implement idempotency keys in a REST API?

32. How would you version a public API without breaking existing clients?

33. What is the difference between serializer validation and model validation? Where should business rules be enforced?

34. How would you prevent users from modifying fields that they are allowed to read but not write?

35. How would you implement cursor pagination, and when is it preferable to offset pagination?

36. Why can offset pagination become increasingly expensive on a large database table?

37. How would you design API rate limiting for an endpoint used by millions of users?

38. How would you return consistent API errors across dozens of Django services?

39. How would you prevent an API endpoint from becoming a bottleneck when clients request extremely large datasets?

40. Suppose a DRF endpoint has gone from 100 ms to 2 seconds after a new feature was deployed. How would you systematically identify the cause?

---

# 4. SQL and database engineering — 15 questions

41. Explain database indexes. What makes an index improve performance, and what are its costs?

42. Why might adding an index actually make a system slower?

43. What is a composite index, and why does column ordering matter?

44. Explain database normalization and denormalization. When would you deliberately denormalize a schema?

45. Explain the difference between `INNER JOIN`, `LEFT JOIN`, and `FULL OUTER JOIN`.

46. What is a transaction? Explain the ACID properties.

47. Explain the four standard transaction isolation levels and the anomalies they prevent.

48. What are dirty reads, non-repeatable reads, and phantom reads?

49. What is a database deadlock? How can an application prevent or recover from one?

50. Consider two concurrent requests:

```text
Request A: read balance = $100
Request B: read balance = $100
Request A: subtract $80
Request B: subtract $70
```

How could the system end up with an incorrect balance, and how would you prevent it?

51. What is optimistic locking? When would you use it instead of pessimistic locking?

52. Explain `SELECT ... FOR UPDATE`. What problem does it solve?

53. How does connection pooling work, and why can too many database connections bring down a production system?

54. A PostgreSQL query takes 5 seconds despite having an apparently appropriate index. How would you investigate it?

55. How would you safely migrate a large production database schema without causing significant downtime?

---

# 5. Django ORM — 10 questions

56. What SQL is approximately generated by:

```python
User.objects.filter(orders__status="completed").select_related("profile")
```

57. Explain the difference between `filter()`, `get()`, `first()`, and `exists()` from both behavioral and performance perspectives.

58. When would `values()` or `values_list()` be preferable to returning Django model instances?

59. What is `bulk_create()`? What important Django model behavior can you lose when using it?

60. What are the risks of using `bulk_update()` for business-critical data?

61. How would you perform an atomic update such as:

```python
account.balance -= amount
```

without suffering from a race condition?

62. What is `F()` expression in Django, and why is it useful for concurrent updates?

63. What happens if you evaluate a QuerySet inside a loop that itself causes additional queries?

64. How would you identify the exact SQL generated by a problematic Django QuerySet?

65. How would you optimize a Django endpoint that performs 300 database queries for a single request?

---

# 6. Distributed systems, concurrency and scalability — 10 questions

66. What does "stateless backend" actually mean, and why is statelessness useful when horizontally scaling Django?

67. What happens when two Kubernetes pods simultaneously process the same logical job?

68. What is a race condition? Give a backend example that is not related to threads.

69. What is eventual consistency? Where would you accept it in a financial platform, and where would you absolutely not?

70. Explain the difference between horizontal and vertical scaling.

71. What is a distributed lock? What problems can occur when implementing one using Redis?

72. What is the CAP theorem, and what does it actually mean in practical system design?

73. Explain idempotency in distributed systems. Why is it especially important for payments, withdrawals, deposits, and blockchain transactions?

74. Suppose your API successfully submits a blockchain transaction but crashes before storing the transaction hash in PostgreSQL. How should the system recover?

75. Design a system where 100,000 users can simultaneously submit orders without overwhelming the database or matching engine.

---

# 7. Docker, Kubernetes and Linux — 10 questions

76. What is the difference between a Docker image and a container?

77. How would you reduce the size and attack surface of a production Django Docker image?

78. What should and should not be included in a Docker image for a Django application?

79. Explain Kubernetes Pods, Deployments, Services, ConfigMaps, and Secrets.

80. What happens when a Kubernetes pod crashes? How does Kubernetes determine what to do?

81. What is the difference between a Kubernetes liveness probe and readiness probe?

82. Why can an incorrectly configured liveness probe cause a production outage?

83. Your Django application works perfectly inside Docker but becomes extremely slow in Kubernetes. How would you investigate it?

84. A Kubernetes deployment repeatedly enters `CrashLoopBackOff`. What would you inspect first?

85. Explain the difference between CPU limits, CPU requests, memory limits, and memory requests in Kubernetes.

---

# 8. Testing, CI/CD and production engineering — 5 questions

86. What is the difference between unit, integration, functional, and end-to-end tests?

87. What should be mocked in a Django unit test, and what should generally not be mocked?

88. How would you test a Django service responsible for transferring money between two accounts?

89. Design a CI/CD pipeline for a Django application that performs tests, builds Docker images, runs migrations, and deploys to Kubernetes.

90. How would you deploy a breaking database/schema change without taking the application offline?

---

# 9. Kafka, observability and Elastic Stack — 5 questions

91. Explain Kafka topics, partitions, offsets, producers, and consumers.

92. Why does Kafka partitioning affect ordering?

93. What happens if a Kafka consumer processes a message successfully but crashes before committing its offset?

94. How would you design a Kafka-based event-processing system where duplicate messages are possible?

95. Your API latency suddenly increases in production. How would you use logs, metrics, traces, and APM to determine whether the problem is Django, PostgreSQL, Redis, Kafka, or an external service?

---

# 10. Blockchain/backend integration — 5 questions

96. How would you design a Django service that communicates with a blockchain node to monitor deposits and withdrawals?

97. What is the difference between a blockchain transaction being submitted, included in a block, and considered sufficiently confirmed?

98. How would you handle blockchain reorganizations/reorgs when your database has already credited a user's deposit?

99. Suppose your withdrawal service sends a blockchain transaction, times out waiting for the node response, and does not know whether the transaction was actually broadcast. How would you make the system safe and recoverable?

100. Design the backend architecture for a crypto exchange handling deposits, withdrawals, balances, blockchain synchronization, orders, and transaction history. Identify where PostgreSQL, Redis, Kafka, Django, workers, and blockchain nodes would fit, and explain which components must provide strong consistency versus eventual consistency.

## What these questions are actually testing

For this particular job description, the strongest candidates should demonstrate competence across five layers:

| Layer               | What a strong candidate should understand                           |
| ------------------- | ------------------------------------------------------------------- |
| Python/Django       | Language internals, ORM, middleware, architecture, DRF              |
| Database            | PostgreSQL, transactions, indexes, locking, concurrency             |
| Distributed systems | Idempotency, queues, race conditions, consistency, failure recovery |
| Infrastructure      | Linux, Docker, Kubernetes, CI/CD, observability                     |
| Blockchain          | Nodes, confirmations, reorgs, transaction lifecycle, reconciliation |

The most discriminating questions for a **3+ year Django engineer** are approximately **30, 31, 35, 40, 49, 50, 53, 61, 66, 68, 73, 74, 82, 89, 93, 95, 98, 99, and 100**. A candidate who can answer these rigorously is demonstrating substantially more than Django/DRF familiarity; they are demonstrating production backend engineering ability.

import asyncio
import logging
import typing

import aiokafka

Key: typing.TypeAlias = typing.Optional[bytes]
Value: typing.TypeAlias = typing.Optional[bytes]
Handler: typing.TypeAlias = typing.Callable[[Key, Value], typing.Awaitable[None]]


class ConsumerApplication:
    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        security_protocol: str = "PLAINTEXT",
        sasl_mechanism: str = "PLAIN",
        sasl_plain_username: str = "",
        sasl_plain_password: str = "",
    ):
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._security_protocol = security_protocol
        self._sasl_mechanism = sasl_mechanism
        self._sasl_plain_username = sasl_plain_username
        self._sasl_plain_password = sasl_plain_password

    @staticmethod
    async def _consume(
        consumer: aiokafka.AIOKafkaConsumer,
        handler: Handler,
        consumer_timeout_ms: int,
        consumer_batch_size: int,
        logger: logging.Logger,
    ):
        while True:
            # Читаем пачку сообщений. Делаем это именно таким образом потому, что не хотим, чтобы происходил autocommit
            records = await consumer.getmany(
                timeout_ms=consumer_timeout_ms,
                max_records=consumer_batch_size,
            )
            for tp, messages in records.items():
                if not messages:
                    logger.info("No messages received, sleep")
                    await asyncio.sleep(consumer_timeout_ms / 1000)
                    continue

                for msg in messages:
                    logger.info(
                        f"Received message from {msg.topic}",
                        extra={"topic": msg.topic},
                    )
                    # До победного пытаемся обработать сообщение
                    await handler(msg.key, msg.value)
                    # Делаем commit только по тем сообщениям, которые обработали
                    await consumer.commit({tp: msg.offset + 1})
                    logger.info(
                        f"Offset {msg.offset + 1} for topic {msg.topic} committed",
                    )

    async def start(
        self,
        consumer_name: str,
        topics: list[str],
        handler: Handler,
        consumer_batch_size: int = 100,
        consumer_timeout_ms: int = 500,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        """Данный метод является единицей, которую можно запускать в отдельном потоке."""
        loop = loop or asyncio.get_event_loop()
        # Создаем консьюмера в группе
        logger = logging.getLogger(f"kafka-consumer[{consumer_name}]")

        logger.info(
            f"Starting consuming topics {topics} on servers {self._bootstrap_servers} from group {self._group_id}",
        )
        consumer = aiokafka.AIOKafkaConsumer(
            *topics,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            fetch_max_wait_ms=consumer_timeout_ms,
            enable_auto_commit=False,
            security_protocol=self._security_protocol,
            sasl_mechanism=self._sasl_mechanism,
            sasl_plain_username=self._sasl_plain_username,
            sasl_plain_password=self._sasl_plain_password,
            loop=loop,
        )

        await consumer.start()
        try:
            await self._consume(
                consumer,
                handler,
                consumer_timeout_ms,
                consumer_batch_size,
                logger,
            )
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            raise
        finally:
            await consumer.stop()

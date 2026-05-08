package com.aiops.scheduler.lock;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * Phase 3 — Redis-backed distributed lock so multiple scheduler pods don't
 * fire the same {@code @Scheduled} job or the same patrol concurrently.
 *
 * <p>Acquisition: {@code SET key token NX EX ttl}. The {@code token} is a
 * fresh UUID so {@link #release(String, String)} only deletes the key when
 * the value still matches — protects against the case where our TTL
 * expired, another pod re-acquired, and we'd otherwise stomp its lock when
 * we belatedly call release.
 *
 * <p>Fail-open contract: if Redis is unreachable / errors, the helper
 * {@link #runWithLock} logs a warning and runs the body anyway. Single-pod
 * deployments where Redis blips for a few seconds are MORE harmed by
 * scheduled jobs stopping than by running unprotected. Set
 * {@code aiops.lock.fail-open=false} to flip to the safe-but-blocky
 * behaviour.
 */
@Slf4j
@Service
public class DistributedLockService {

	private static final RedisScript<Long> RELEASE_SCRIPT = new DefaultRedisScript<>(
			"if redis.call('GET', KEYS[1]) == ARGV[1] then " +
					"return redis.call('DEL', KEYS[1]) else return 0 end",
			Long.class);

	private final StringRedisTemplate redis;
	private final boolean failOpen;
	private final String namespace;

	public DistributedLockService(StringRedisTemplate redis,
	                              @Value("${aiops.lock.fail-open:true}") boolean failOpen,
	                              @Value("${aiops.lock.namespace:aiops:lock}") String namespace) {
		this.redis = redis;
		this.failOpen = failOpen;
		this.namespace = namespace;
	}

	/**
	 * Try to acquire the lock. Returns the caller's release token on
	 * success, or empty if another holder still has it.
	 */
	public Optional<String> tryAcquire(String key, Duration ttl) {
		String fullKey = nsKey(key);
		String token = UUID.randomUUID().toString();
		Boolean ok = redis.opsForValue().setIfAbsent(fullKey, token, ttl);
		return Boolean.TRUE.equals(ok) ? Optional.of(token) : Optional.empty();
	}

	/** Atomic release via Lua — only DEL if the stored token matches ours. */
	public void release(String key, String token) {
		String fullKey = nsKey(key);
		redis.execute(RELEASE_SCRIPT, List.of(fullKey), token);
	}

	/**
	 * Wrap a {@code Runnable} in acquire → run → release.
	 *
	 * @return {@code true} if the body ran (either we got the lock OR
	 *         we're in fail-open and Redis errored), {@code false} if we
	 *         skipped because another pod has the lock.
	 */
	public boolean runWithLock(String key, Duration ttl, Runnable body) {
		Optional<String> token;
		try {
			token = tryAcquire(key, ttl);
		} catch (Exception e) {
			if (failOpen) {
				log.warn("Redis tryAcquire failed for {} — running anyway (fail-open=true): {}",
						key, e.getMessage());
				body.run();
				return true;
			}
			log.warn("Redis tryAcquire failed for {} — skipping (fail-open=false): {}",
					key, e.getMessage());
			return false;
		}

		if (token.isEmpty()) {
			log.debug("lock {} not acquired — another pod is running this", key);
			return false;
		}

		try {
			body.run();
			return true;
		} finally {
			try {
				release(key, token.get());
			} catch (Exception e) {
				log.warn("Redis release failed for {} (TTL will reclaim): {}", key, e.getMessage());
			}
		}
	}

	private String nsKey(String key) {
		return namespace + ":" + key;
	}
}

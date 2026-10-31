<?php

/**
 * Minimal .env loader shared by all config files.
 */

if (!function_exists('furyo_load_env')) {
    function furyo_load_env(string $envFile): void
    {
        if (!is_file($envFile) || !is_readable($envFile)) {
            return;
        }

        $lines = file($envFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        if ($lines === false) {
            return;
        }

        foreach ($lines as $line) {
            $line = trim($line);
            $line = preg_replace('/^\xEF\xBB\xBF/', '', $line) ?? $line;

            if ($line === '' || strpos($line, '#') === 0 || strpos($line, '=') === false) {
                continue;
            }

            if (strpos($line, 'export ') === 0) {
                $line = trim(substr($line, 7));
            }

            [$key, $value] = explode('=', $line, 2);
            $key = trim($key);
            $value = trim($value);

            if ($key === '') {
                continue;
            }

            $quote = $value[0] ?? '';
            if (($quote === '"' || $quote === "'") && substr($value, -1) === $quote) {
                $value = substr($value, 1, -1);
            }

            $_ENV[$key] = $value;
            $_SERVER[$key] = $_SERVER[$key] ?? $value;
            putenv($key . '=' . $value);
        }
    }
}

if (!function_exists('furyo_env')) {
    function furyo_env(string $key, ?string $default = null): ?string
    {
        if (array_key_exists($key, $_ENV) && $_ENV[$key] !== '') {
            return (string)$_ENV[$key];
        }

        $value = getenv($key);
        if ($value !== false && $value !== '') {
            return (string)$value;
        }

        if (array_key_exists($key, $_SERVER) && $_SERVER[$key] !== '') {
            return (string)$_SERVER[$key];
        }

        $redirectKey = 'REDIRECT_' . $key;
        if (array_key_exists($redirectKey, $_SERVER) && $_SERVER[$redirectKey] !== '') {
            return (string)$_SERVER[$redirectKey];
        }

        return $default;
    }
}

furyo_load_env(__DIR__ . '/.env');

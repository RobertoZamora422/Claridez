# Spike técnico de aislamiento multiempresa

Este directorio contiene código experimental y desechable de la Iteración 3. No es una
implementación productiva de organizaciones, membresías, autorización ni permisos.

## Aislamiento

- La única base admitida es `claridez_tenancy_spike`.
- La configuración normal de Claridez no carga esta aplicación ni sus migraciones.
- El runner crea, migra, prueba y elimina la base en un bloque `finally`.
- `claridez_migrator` ejecuta las migraciones y conserva la propiedad de las tablas.
- `claridez_app` y `claridez_test_runner` prueban el comportamiento como no propietarios.
- pytest usa una configuración propia y desactiva el plugin `pytest-django`; no crea bases ni
  ejecuta migraciones.

La base no se conserva después de una ejecución, incluso si una prueba falla. Una ejecución no se
considera válida si `claridez_tenancy_spike` continúa existiendo.

## Comandos

Desde la raíz:

```text
npm run tenancy-spike:run
```

Ese es el comando reproducible preferido. Los comandos parciales existen para diagnóstico:

```text
npm run tenancy-spike:prepare
npm run tenancy-spike:test
npm run tenancy-spike:benchmark
npm run tenancy-spike:cleanup
```

`prepare`, `test` y `benchmark` no reemplazan el ciclo protegido completo. `cleanup` exige la
confirmación explícita y solo elimina la base exacta del spike.

## Evidencia

Los artefactos detallados se escriben en `tmp/tenancy-spike/`, están ignorados por Git y no deben
editarse manualmente:

- `results.json`;
- `test-evidence.json`;
- `coverage.xml`;
- `htmlcov/`.

La evidencia permanente, resumida y sin identificadores sintéticos innecesarios, se conserva en
[TENANCY_SPIKE_RESULTS.md](../../../../docs/architecture/TENANCY_SPIKE_RESULTS.md). El protocolo está
en [TENANCY_SPIKE_PROTOCOL.md](../../../../docs/architecture/TENANCY_SPIKE_PROTOCOL.md) y la decisión
pendiente en [ADR 0009](../../../../docs/adr/0009-tenant-isolation-strategy.md).

## Clasificación del código

- `models.py`, migraciones, settings, helpers, servicios, benchmark, runner y pruebas: código
  experimental que debe eliminarse al cerrar la revisión arquitectónica.
- `context.py`, `managers.py` y `services.py`: ejemplos que pueden informar una reimplementación,
  pero no deben copiarse automáticamente al producto.
- Documentos de protocolo, resultados, amenazas y ADR: evidencia permanente.

El GUC `claridez.organization_id` transporta un contexto técnico. No prueba membresía ni autoriza a
un actor. Toda integración futura deberá validar primero la pertenencia y los permisos.

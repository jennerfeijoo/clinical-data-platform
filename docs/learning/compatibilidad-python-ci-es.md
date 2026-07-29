# Compatibilidad de Python y CI multiversión

## Objetivo

Este hito responde una pregunta concreta:

> ¿Cómo sabemos que la plataforma funciona en más de una versión de Python?

La respuesta no puede ser solamente «el código parece compatible». La compatibilidad se convierte en una condición ejecutable de GitHub Actions.

## Versiones soportadas

La versión `0.18.0` declara:

```toml
requires-python = ">=3.11,<3.15"
```

Esto significa:

| Versión | Estado en el proyecto |
|---|---|
| Python 3.11 | mínima y de referencia |
| Python 3.12 | probada en CI |
| Python 3.13 | probada en CI |
| Python 3.14 | probada en CI |
| Python 3.15+ | bloqueada hasta validación futura |

El límite superior evita que el paquete se instale silenciosamente en una versión todavía no verificada.

## Dos niveles de CI

### 1. Trabajo de referencia en Python 3.11

Python 3.11 ejecuta el control más amplio:

```text
instalación
→ pip check
→ contratos
→ Synthea
→ dos cohortes
→ reportes de calidad
→ migraciones
→ raw landing zone
→ Ruff
→ mypy
→ pytest con cobertura ≥90%
→ Docker
→ smoke tests del contenedor
```

También es la versión usada por el benchmark. Mantener una versión fija evita confundir una diferencia de rendimiento del código con una diferencia del intérprete.

### 2. Matriz de compatibilidad

GitHub Actions crea tres trabajos adicionales:

```text
Python 3.12 + PostgreSQL + suite completa
Python 3.13 + PostgreSQL + suite completa
Python 3.14 + PostgreSQL + suite completa
```

Cada trabajo usa un runner y una base de datos separados. Por tanto, las pruebas no comparten esquemas ni estados residuales.

## Por qué se usa `fail-fast: false`

Con el comportamiento fail-fast, el primer fallo podría cancelar el resto de la matriz. Aquí se necesita conocer el resultado de todas las versiones.

Ejemplo:

```text
3.12  pasa
3.13  falla
3.14  pasa
```

Este resultado indica una incompatibilidad específica de 3.13. Cancelar 3.14 habría ocultado información importante.

## Qué valida cada versión

No se ejecuta únicamente `import clinical_data_platform`. Cada versión debe superar:

1. instalación editable del paquete;
2. resolución coherente de dependencias mediante `pip check`;
3. versión correcta del intérprete y del paquete;
4. carga de los contratos ejecutables;
5. descubrimiento de los perfiles Synthea;
6. migración y validación de PostgreSQL;
7. pruebas unitarias y de integración;
8. cobertura total mínima del 90%.

Esto permite detectar problemas como:

- cambios del lenguaje entre versiones;
- dependencias sin wheel compatible;
- diferencias de tipado o bibliotecas estándar;
- errores de serialización o fechas;
- incompatibilidades de psycopg;
- rutas PostgreSQL que solo fallan en una versión.

## Prueba contra desalineación

El archivo:

```text
tests/test_python_compatibility_policy.py
```

comprueba que la metadata y los workflows continúen alineados.

Por ejemplo, fallará si alguien:

- añade Python 3.15 al workflow sin modificar `requires-python`;
- elimina Python 3.14 de la matriz pero mantiene su classifier;
- cambia el benchmark a otra versión sin documentarlo;
- elimina `pip check` o `fail-fast: false`.

Esta prueba no sustituye a la matriz. Solo detecta inconsistencias de configuración.

## Cómo reproducir localmente

En un entorno concreto:

```powershell
python --version
python -m pip install -e ".[dev]"
python -m pip check
python -m pytest
```

Para probar otra versión se debe crear otro entorno virtual con ese intérprete. Un único entorno local no demuestra compatibilidad multiversión.

## Cómo añadir una versión futura

Para incorporar Python 3.15 será necesario:

```text
matriz CI
+ metadata requires-python
+ classifiers
+ suite PostgreSQL completa
+ cobertura ≥90%
+ documentación
```

Solo después de que todo pase debe eliminarse el límite `<3.15` o desplazarse a `<3.16`.

## Límites

El hito no demuestra compatibilidad con:

- PyPy u otras implementaciones;
- Windows o macOS;
- todas las arquitecturas de CPU;
- versiones futuras de las dependencias;
- datos clínicos reales;
- entornos hospitalarios o regulatorios.

Demuestra compatibilidad reproducible con CPython 3.11–3.14, PostgreSQL 16 y las dependencias resueltas durante CI.

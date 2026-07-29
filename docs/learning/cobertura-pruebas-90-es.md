# Cobertura de pruebas obligatoria del 90%

## 1. Qué problema resuelve este hito

Una plataforma de datos puede acumular muchas funciones que parecen correctas pero nunca se ejecutan durante las pruebas. Cuando eso ocurre, una modificación pequeña puede romper rutas importantes sin que CI lo detecte.

La cobertura cuantifica qué proporción de las sentencias Python fue ejecutada al menos una vez por la suite de pruebas.

En esta versión, el repositorio pasa de:

```text
82% de cobertura
117 pruebas
```

a:

```text
90,14% de cobertura de sentencias
142 pruebas
```

El umbral mínimo queda fijado en 90%. Una ejecución por debajo de ese valor termina con error.

## 2. Qué significa cobertura de sentencias

Supongamos esta función:

```python
def classify(value: int) -> str:
    if value >= 0:
        return "non-negative"
    return "negative"
```

Una prueba que use `value=5` ejecutará la condición y la primera devolución, pero no la segunda. La función fue llamada, aunque no todo su comportamiento fue cubierto.

La cobertura de sentencias responde:

> ¿Qué líneas ejecutables fueron recorridas por al menos una prueba?

No demuestra que las aserciones sean correctas ni que se hayan evaluado todas las combinaciones de entrada.

## 3. Cómo se aplica el umbral

La configuración está centralizada en `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "-ra --strict-markers --cov=clinical_data_platform --cov-report=term-missing --cov-fail-under=90"

[tool.coverage.report]
fail_under = 90
show_missing = true
```

Por eso basta ejecutar:

```powershell
python -m pytest
```

Pytest ejecuta las pruebas, calcula la cobertura, muestra las líneas no cubiertas y devuelve un código distinto de cero cuando el total es inferior al 90%.

CI utiliza la misma configuración. No existe un umbral más débil para el entorno local ni una regla separada que pueda quedar desactualizada.

## 4. Qué se probó realmente

### Contratos y validación

Se ejecutan realmente:

```text
listado de contratos
visualización JSON de contratos
validación de los seis contratos
captura raw de un CSV sintético
verificación del recibo raw
validación genérica de pacientes
```

Estas pruebas utilizan archivos sintéticos del repositorio y directorios temporales.

### Flujo Synthea

Se ejecutan realmente sobre fixtures pequeños:

```text
carga del perfil fijado
adaptación de seis CSV
verificación del manifiesto adaptado
comparación de dos cohortes
reporte de attrition y missingness
```

No se ejecuta el generador Java completo en las pruebas unitarias. Esa frontera se sustituye por un doble controlado porque el objetivo es comprobar la orquestación del comando, no volver a generar poblaciones completas en cada commit.

### Interfaces CLI

Se prueban los comandos principales de:

```text
clinical-data
clinical-data-cohort
clinical-data-benchmark
```

Las pruebas comprueban argumentos, dependencias llamadas, salidas impresas, valores devueltos y propagación de errores.

### Demo y logging

El flujo `run_demo` se recorre de principio a fin con resúmenes deterministas para comprobar:

```text
validación de todas las entidades
migración
persistencia
construcción de cohorte
identificadores devueltos
```

El entrypoint se prueba tanto cuando el comando termina correctamente como cuando lanza una excepción. En ambos casos se verifican los eventos de logging correspondientes.

## 5. Por qué también se prueban los fallos

Las rutas nominales ya estaban razonablemente cubiertas. Para llegar a un nivel útil era necesario probar también los límites de confianza.

Se añadieron casos para:

```text
TOML inválido o no UTF-8
tablas requeridas ausentes
tipos incorrectos
versión de esquema no soportada
fecha no ISO
población no positiva
semillas negativas
Java demasiado antiguo
más de un hilo
historial truncado
manifiesto JSON inválido
CSV ausente o con header inesperado
ejecutable no encontrado
subproceso con código de error
checkout sin Git
tag incorrecto
worktree con modificaciones
texto de versión Java no interpretable
```

Estas rutas importan porque una plataforma de datos debe fallar de manera explícita cuando una entrada o dependencia deja de cumplir su contrato.

## 6. Pruebas reales frente a mocks

Un mock no debe utilizarse simplemente para aumentar cobertura. Se usa cuando existe una frontera externa que haría la prueba lenta, no determinista o dependiente de infraestructura innecesaria.

Ejemplos de fronteras sustituidas:

```text
Java y generación completa de Synthea
comandos Git
algunos comandos PostgreSQL
medición temporal del benchmark
```

La lógica interna que transforma artefactos sintéticos se ejecuta realmente siempre que es razonable.

Una prueba con mock sigue siendo útil cuando verifica:

```text
qué función fue llamada
con qué argumentos
en qué orden
qué resultado se presenta al usuario
cómo se propaga un fallo
```

No permite afirmar que la dependencia externa fue validada.

## 7. Qué no demuestra el 90%

El porcentaje no demuestra:

```text
corrección clínica
seguridad completa
ausencia de bugs
validez epidemiológica
rendimiento en producción
comportamiento concurrente
preparación para PHI
cumplimiento regulatorio
```

Tampoco significa que cada línea tenga una buena aserción. Una prueba podría ejecutar una función sin comprobar suficientemente su resultado.

Por eso el porcentaje debe interpretarse junto con la calidad de las aserciones, las pruebas PostgreSQL, los smoke tests de contenedor y los workflows reproducibles.

## 8. Cómo mantener el umbral

Antes de enviar cambios:

```powershell
python -m ruff check .
python -m mypy src
python -m pytest
```

Cuando se añade código nuevo, la salida de coverage muestra las líneas que quedaron sin recorrer.

La respuesta normal debe ser una de estas:

```text
añadir una prueba de comportamiento
eliminar código obsoleto o inalcanzable
refactorizar una función difícil de probar
```

No debe resolverse reduciendo el umbral ni excluyendo módulos completos.

## 9. Ejercicio de lectura del reporte

Una línea como esta:

```text
synthea.py    642    75    88%
```

significa:

```text
642 sentencias medidas
75 sentencias no ejecutadas
567 sentencias ejecutadas
88% aproximado de cobertura
```

El total del proyecto se calcula sobre todas las sentencias medidas, no como promedio simple de los porcentajes de los módulos.

## 10. Resultado arquitectónico

Este hito no agrega tablas ni una migración V009. Agrega una política de calidad ejecutable:

```text
cambio de código
→ Ruff
→ mypy estricto
→ pytest
→ PostgreSQL integration
→ coverage total
→ fallo si coverage < 90%
→ Docker y smoke tests
```

La cobertura deja de ser una cifra informativa y pasa a ser una condición verificable para integrar cambios.

## 11. Límite del proyecto

Todos los datos utilizados siguen siendo sintéticos. Este hito fortalece la ingeniería del repositorio, pero no cambia su condición de proyecto educativo y demostrativo, no preparado para datos identificables ni decisiones clínicas.

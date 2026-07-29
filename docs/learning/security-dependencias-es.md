# Seguridad automatizada y auditoría de dependencias

## 1. Qué problema resuelve este hito

Las pruebas funcionales pueden confirmar que el software hace lo esperado, pero no responden por sí solas a preguntas como:

```text
¿Una dependencia instalada tiene una vulnerabilidad conocida?
¿El código contiene un patrón inseguro?
¿Un pull request introduce una biblioteca vulnerable?
¿La imagen Docker contiene paquetes del sistema vulnerables?
¿Las acciones de GitHub pueden cambiar sin revisión?
```

La versión `0.19.0` incorpora controles separados para estas superficies.

## 2. Modelo de defensa en capas

```text
pyproject.toml
→ resolución de dependencias
→ pip-audit

src/
→ Bandit
→ CodeQL

pull request
→ dependency review

Dockerfile
→ build de imagen
→ Trivy

versiones futuras
→ Dependabot
```

Ningún escáner sustituye a los demás. Cada uno observa una parte distinta del sistema.

## 3. `pip-audit`

`pip-audit` compara las versiones instaladas con bases de vulnerabilidades conocidas.

La ejecución utilizada es conceptualmente:

```bash
python -m pip_audit --local
```

Puede detectar que una versión concreta de una biblioteca aparece asociada a un identificador de vulnerabilidad publicado.

No analiza la lógica del proyecto y no demuestra que una dependencia sea confiable. Solo trabaja con vulnerabilidades conocidas por sus fuentes de datos.

Además se genera un SBOM CycloneDX:

```text
python-sbom.cdx.json
```

El SBOM es un inventario de componentes del entorno resuelto. No es una prueba de seguridad y tampoco reemplaza un lockfile.

## 4. Bandit

Bandit analiza el código Python buscando patrones potencialmente inseguros.

La política del proyecto exige:

```text
severidad mínima: media
confianza mínima: media
```

Comando:

```bash
python -m bandit -r src -ll -ii
```

Esta selección evita bloquear el repositorio por advertencias de baja confianza, pero sigue tratando como fallo los hallazgos más creíbles.

## 5. CodeQL

CodeQL representa el código como datos consultables y aplica consultas de seguridad sobre flujos y relaciones del programa.

En el repositorio se utiliza:

```text
lenguaje: Python
query suite: security-extended
```

Bandit y CodeQL no son redundantes. Bandit se orienta principalmente a patrones locales; CodeQL puede estudiar relaciones y propagaciones más amplias.

## 6. Revisión de dependencias en pull requests

La Dependency Review Action analiza qué dependencias añade o modifica un pull request.

La política es:

```text
vulnerabilidad nueva alta o crítica
→ pull request bloqueado
```

Esto es distinto de auditar el entorno actual. La revisión se centra en el cambio introducido.

## 7. Trivy y la imagen Docker

La plataforma construye la imagen y analiza:

```text
paquetes del sistema operativo
bibliotecas del lenguaje
```

Se bloquean vulnerabilidades:

```text
HIGH
CRITICAL
```

La política ignora como condición de fallo los hallazgos sin corrección disponible. Siguen siendo visibles en la salida. “Sin corrección” no significa “sin riesgo”; significa que el pipeline no puede resolverlos mediante una actualización disponible en ese momento.

## 8. Dependabot

Dependabot revisa semanalmente:

```text
pip
GitHub Actions
Docker
```

Dependabot no fusiona cambios automáticamente. Abre pull requests que deben pasar revisión y CI.

## 9. Acciones fijadas por SHA

Una referencia mutable como:

```yaml
uses: actions/checkout@v4
```

puede apuntar a contenido diferente en el futuro.

La plataforma utiliza:

```yaml
uses: actions/checkout@<SHA completo> # versión legible
```

El SHA fija el contenido exacto ejecutado. El comentario conserva la versión humana. Una prueba recorre todos los workflows y rechaza referencias que no utilicen 40 caracteres hexadecimales.

## 10. Por qué existe una ejecución programada

Una dependencia puede pasar hoy y aparecer mañana en una nueva alerta, aunque el repositorio no cambie.

Por eso el workflow se ejecuta:

```text
cada pull request
cada push a main
manualmente
semanalmente
```

## 11. Evidencia generada

Los jobs publican artefactos como:

```text
pip-audit.json
python-sbom.cdx.json
bandit.json
```

Los logs de CodeQL, dependency review y Trivy quedan asociados a la ejecución de GitHub Actions.

## 12. Ejecución local

```powershell
python -m pip install -e ".[dev,security]"
python -m pip check
python -m pip_audit --local --progress-spinner off
python -m bandit -r src -ll -ii
```

La ejecución local puede diferir de CI porque las versiones transitivas y el sistema operativo pueden ser distintos.

## 13. Preguntas que debes poder responder

1. ¿Qué diferencia existe entre una prueba funcional y un escáner de vulnerabilidades?
2. ¿Qué analiza `pip-audit` y qué no analiza?
3. ¿Por qué un SBOM no es un lockfile?
4. ¿Qué significan severidad y confianza en Bandit?
5. ¿Por qué se mantienen Bandit y CodeQL?
6. ¿Qué diferencia existe entre dependency review y `pip-audit`?
7. ¿Qué componentes inspecciona Trivy en la imagen?
8. ¿Por qué se fijan las acciones mediante SHA completo?
9. ¿Por qué los escaneos deben repetirse aunque el código no cambie?
10. ¿Por qué un workflow verde no demuestra seguridad total?

## 14. Explicación profesional defendible

> La plataforma aplica controles de seguridad en varias capas. `pip-audit` compara el entorno Python con vulnerabilidades conocidas y genera un SBOM CycloneDX. Bandit y CodeQL realizan análisis estático con modelos diferentes. Dependency Review bloquea nuevas dependencias con vulnerabilidades altas o críticas, mientras Trivy inspecciona la imagen construida. Dependabot propone actualizaciones semanales y todas las acciones externas están fijadas mediante SHA completo. Estos controles reducen riesgo y generan evidencia, pero no sustituyen revisión manual, modelado de amenazas, pruebas de penetración ni controles para PHI.

## 15. Límites

Este hito no demuestra:

```text
ausencia de vulnerabilidades desconocidas
seguridad de despliegue
cumplimiento regulatorio
preparación para PHI
resistencia completa a ataques de supply chain
seguridad clínica
```

El repositorio continúa limitado a datos sintéticos y aprendizaje de ingeniería.

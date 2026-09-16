# Directorio de pruebas de MoneyPrinterTurbo

Este directorio contiene las pruebas unitarias del proyecto **MoneyPrinterTurbo**.

## Estructura del directorio

- `services/`: pruebas unitarias y de controladores enfocadas en el dominio
  - `test_task.py`: pruebas de la tubería de tareas
  - `test_task_manager.py`: pruebas de colas en memoria y Redis
  - `test_controller_*.py`: pruebas de controladores de la API divididas por dominio del controlador
  - `test_video.py`, `test_voice.py`: pruebas de los servicios multimedia
- `test_main.py`: prueba del punto de entrada de la aplicación

## Ejecutar las pruebas

El conjunto de pruebas de CI usa pytest, que también ejecuta las pruebas existentes de `unittest.TestCase`:

```bash
# Run all tests
uv run python -X utf8 -m pytest -q test

# Run a specific test file
uv run python -X utf8 -m pytest -q test/services/test_video.py

# Run a specific test class
uv run python -X utf8 -m pytest -q test/services/test_video.py::TestVideoService

# Run a specific test method
uv run python -X utf8 -m pytest -q test/services/test_video.py::TestVideoService::test_preprocess_video
```

Para ejecutar la misma verificación de cobertura de ramas que usa CI:

```bash
uv run python -X utf8 -m coverage run -m pytest -q test
uv run python -m coverage report
```

Las pruebas de proveedores en vivo se omiten de forma predeterminada. Para ejecutar pruebas que puedan llamar a servicios externos de TTS o LLM, configura `MPT_RUN_INTEGRATION_TESTS=1` y proporciona las credenciales requeridas del proveedor.

## Agregar nuevas pruebas

Para agregar pruebas de otros componentes, sigue estas pautas:

1. Nombra los archivos `test_<domain>.py` y mantén cada archivo enfocado en un dominio.
2. Divide las suites de controladores amplias en archivos como `test_controller_video.py`.
3. Usa funciones de pytest o `unittest.TestCase`; pytest recoge ambas.
4. Nombra las funciones y métodos de prueba con el prefijo `test_`.

## Recursos de prueba

Coloca en el directorio `test/resources` cualquier archivo de recursos necesario para las pruebas.

"""Runner de tests que deja al proveedor de IA fuera de alcance.

Varios módulos de la suite afirman en su docstring que no hay `OPENAI_API_KEY` en el entorno de
test y que por eso toda llamada al proveedor "cae determinísticamente al error". Eso NO era cierto:
en el servidor de pruebas la clave está en el entorno del contenedor, así que lo único que evitaba
una llamada real —y su costo— era que cada test se acordara de mockear. Un test nuevo que se
olvide gasta tokens de verdad, en silencio, y lo descubre quien mire la factura.

Este runner borra las claves del entorno antes de que corra el primer test, así que una llamada no
mockeada falla con "OPENAI_API_KEY no está configurada" en vez de salir a la red. Convierte en
garantía lo que era una convención, que es justo lo que esos docstrings ya daban por hecho.

Pedido explícito del dueño del repo (2026-10-04): "NO USES LA API DE OPENAI PARA LAS PRUEBAS".
"""
from unittest.mock import patch

from django.test.runner import DiscoverRunner

# Claves que, si están presentes, permiten que un test no mockeado llame a un proveedor de pago.
CLAVES_DE_PROVEEDOR = ('OPENAI_API_KEY',)


class RunnerSinProveedores(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        import os

        # `close_old_connections()` es correcto en un hilo de background real —para eso está— y
        # destructivo dentro de un TestCase: cierra la conexión de la transacción del test. Todo
        # el trabajo pesado de este proyecto corre en hilos que la llaman al entrar y al salir
        # (procesar_extraccion_momento, procesar_analisis_v2, procesar_reporte, …), así que
        # cualquier test que llame a una de esas funciones DIRECTAMENTE —que es la forma honesta
        # de probarlas, sin hilo de por medio— muere con "connection already closed". Es lo que
        # tenía en rojo a los 10 tests de `analitica/tests_v2` desde la entrega del contrato v2.
        # Se neutraliza para toda la corrida: en un test no hay conexiones viejas que reciclar.
        self._parche_conexiones = patch('django.db.close_old_connections')
        self._parche_conexiones.start()

        self.claves_retiradas = {}
        for clave in CLAVES_DE_PROVEEDOR:
            if os.environ.get(clave):
                self.claves_retiradas[clave] = os.environ.pop(clave)
        if self.claves_retiradas:
            print(
                'Tests: se retiraron del entorno '
                f'{", ".join(sorted(self.claves_retiradas))} — ninguna llamada a un proveedor de '
                'pago puede salir de acá (ver config/test_runner.py).'
            )
        super().setup_test_environment(**kwargs)

    def teardown_test_environment(self, **kwargs):
        import os

        super().teardown_test_environment(**kwargs)
        self._parche_conexiones.stop()
        # Se devuelven para no dejar el proceso mutilado si alguien corre tests y después un shell
        # en la misma sesión de Python.
        for clave, valor in getattr(self, 'claves_retiradas', {}).items():
            os.environ[clave] = valor

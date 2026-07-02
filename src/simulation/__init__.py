"""src/simulation — Simulación Monte Carlo del Mundial 2026 (Feature 13).

Paquete que orquesta:
- ``bracket``: derivación de grupos desde fixtures y mapeo del bracket eliminatorio.
- ``standings``: tabla de grupo con desempates deterministas.
- ``montecarlo``: bucle de N simulaciones con muestreo Dixon-Coles.
- ``report``: escritura de ``summary.json`` y ``advancement.csv`` bajo ``data/``.
"""

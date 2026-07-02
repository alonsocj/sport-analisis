"""Paquete de mercados de apuestas derivados del modelo Dixon-Coles (Feature 4).

Expone probabilidades de mercados de goles (over/under, BTTS, totales por
equipo) derivadas de la matriz conjunta de marcadores del modelo entrenado
(feature 3). Sin importaciones de aplicacion: la dependencia es unidireccional
(CLI y app importan src.markets, nunca al reves).
"""

"""R8 — 48 selecciones; anfitrionas marcadas."""

from src.ingestion.teams import all_teams, host_teams, is_host


def test_48_teams_hosts_marked():
    teams = all_teams()
    # R8: exactamente 48 selecciones.
    assert len(teams) == 48
    # Códigos únicos.
    codes = [t.code for t in teams]
    assert len(set(codes)) == 48
    # R8: anfitrionas = MEX, USA, CAN.
    host_codes = {t.code for t in host_teams()}
    assert host_codes == {"USA", "MEX", "CAN"}
    assert is_host("usa") and is_host("MEX") and is_host("CAN")
    assert not is_host("ARG")

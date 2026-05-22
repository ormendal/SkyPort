import time

def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """
    Stampa un resoconto finale personalizzato con il dettaglio di ogni test.
    """
    terminalreporter.section("=== RESOCONTO FINALE DEI TEST ===")
    terminalreporter.write(f"Data/ora: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    
    passed = terminalreporter.stats.get('passed', [])
    failed = terminalreporter.stats.get('failed', [])
    skipped = terminalreporter.stats.get('skipped', [])
    error = terminalreporter.stats.get('error', [])
    
    total = len(passed) + len(failed) + len(skipped) + len(error)
    
    terminalreporter.write(f"Test eseguiti: {total}\n")
    terminalreporter.write(f"✔ Passati:     {len(passed)}\n")
    terminalreporter.write(f"✘ Falliti:     {len(failed)}\n")
    terminalreporter.write(f"⚠ Saltati:     {len(skipped)}\n")
    terminalreporter.write(f"⚠ Errori:      {len(error)}\n\n")
    
    if passed:
        terminalreporter.write("--- PASSATI ---\n")
        for rep in passed:
            terminalreporter.write(f"  ✔ {rep.nodeid}\n")
    
    if failed:
        terminalreporter.write("\n--- FALLITI ---\n")
        for rep in failed:
            terminalreporter.write(f"  ✘ {rep.nodeid}\n")
            if hasattr(rep, 'longrepr'):
                terminalreporter.write(f"    Motivo: {rep.longreprtext}\n")
    
    if error:
        terminalreporter.write("\n--- ERRORI ---\n")
        for rep in error:
            terminalreporter.write(f"  ⚠ {rep.nodeid}\n")
    if skipped:
        terminalreporter.write("\n--- SALTATI ---\n")
        for rep in skipped:
            terminalreporter.write(f"  ⚠ {rep.nodeid}\n")
    
    if exitstatus == 0:
        terminalreporter.write("\n✅ TUTTI I TEST SONO PASSATI\n")
    else:
        terminalreporter.write("\n❌ CI SONO TEST FALLITI\n")
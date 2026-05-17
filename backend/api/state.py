"""
Módulo de estado global em memória.
Armazena informações efêmeras como o status das tarefas em background (downloads e sincronizações).
"""

from typing import Dict, Any

# Dicionário em memória para rastrear o progresso e status das tarefas
# Formato: {"task_id_123": {"status": "running", "message": "...", "progress": 50}}
tasks_status: Dict[str, Dict[str, Any]] = {}

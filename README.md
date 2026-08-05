# Gestionale Funds 2.0

## File da caricare su GitHub
- app.py
- clients.json
- operations.json
- requirements.txt
- cartella .streamlit/config.toml

## Pubblicazione
Per evitare l'incompatibilità riscontrata con Python 3.14:
1. Elimina l'app Streamlit che è andata in errore.
2. Crea nuovamente l'app.
3. Apri Advanced settings.
4. Seleziona Python 3.12.
5. Imposta app.py come Main file path.
6. Aggiungi nei Secrets:
   APP_PASSWORD = "la-tua-password"
7. Esegui Deploy.

Se non configuri APP_PASSWORD nei Secrets, la password provvisoria è: Funds2026
Cambiala immediatamente prima di condividere il link.

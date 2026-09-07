# uns_factory_agent

Read-only Factory Copilot agent for the UNS console. Answers plant questions by calling
allowlisted SQL against the Asset Model and historian, plus GraphQL for live UNS Nodes and
Alert Rules. Conversation threads live in the `copilot` schema on `uns_historian`. Plant SQL
uses the shared `uns_dbuser` role; `sql_guard` blocks anything but a single allowlisted SELECT.

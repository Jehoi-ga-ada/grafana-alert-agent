"""I/O adapters — thin clients over Grafana, VictoriaMetrics, Loki, Discord.

Every client is read-only against infrastructure. The only outbound writes are
the Discord webhook and (elsewhere) the Claude API.
"""

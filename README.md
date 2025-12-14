# sqlit

A simple terminal UI for SQL Server, PostgreSQL, MySQL, SQLite, and more—built for people who just want to run some queries fast.

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

### Multi-database Support
![Database Providers](demo-providers.gif)

### Query History
![Query History](demo-history.gif)


## Features

- **Multi-database support**: SQL Server, PostgreSQL, MySQL, SQLite, MariaDB, Oracle, DuckDB, and CockroachDB
- **SSH tunnel support**: Connect to remote databases through SSH with password or key-based authentication
- **Query history**: Automatically saves queries per connection, searchable and sortable
- Fast and intuitive keyboard only control
- Context based help (no need to memorize tons of hot-keys)
- Browse databases, tables, views, and stored procedures
- Execute SQL queries with syntax highlighting
- Vim-style query editing
- SQL autocomplete for tables, columns, and procedures
- Multiple authentication methods (Windows, SQL Server, Entra ID)
- Save and manage connections
- Responsive terminal UI
- CLI mode for scripting and AI agents
- Themes (Tokyo Night, Nord, and more)
- Auto-detects and installs ODBC drivers (SQL Server)


## Motivation
I usually do my work in the terminal, but I found myself either having to boot up massively bloated GUI's like SSMS or Vscode for the simple task of merely browsing my databases and doing some queries toward them. For the vast majority of my use cases, I never used any of the advanced features for inspection and debugging that SSMS and other feature-rich clients provide. 

I had the unfortunate situation where doing queries became a pain-point due to the massive operation it is to open SSMS and it's lack of intuitive keyboard only navigation.

The problem got severely worse when I switched to Linux and had to rely on VS CODE's SQL extension to access my database. Something was not right.

I tried to use some existing TUI's for SQL, but they were not intuitive for me and I missed the immediate ease of use that other TUI's such as Lazygit provides.

sqlit is a lightweight database TUI that is easy to use and beautiful to look at, just connect and query. It's for you that just wants to run queries toward your database without launching applications that eats your ram and takes time to load up. Sqlit supports SQL Server, PostgreSQL, MySQL, SQLite, MariaDB, Oracle, DuckDB, and CockroachDB, and is designed to make it easy and enjoyable to access your data, not painful.


## Installation

```bash
pip install sqlit-tui
```

For SQL Server, sqlit will detect if you're missing ODBC drivers and help you install them.

For PostgreSQL, CockroachDB, and MySQL, install the optional drivers:

```bash
# PostgreSQL / CockroachDB
pip install psycopg2-binary

# MySQL
pip install mysql-connector-python
```

SQLite works out of the box with no additional dependencies.

## Usage

```bash
sqlit
```

The keybindings are shown at the bottom of the screen.

### CLI

```bash
# Run a query
sqlit query -c "MyConnection" -q "SELECT * FROM Users"

# Output as CSV or JSON
sqlit query -c "MyConnection" -q "SELECT * FROM Users" --format csv
sqlit query -c "MyConnection" -f "script.sql" --format json

# Create connections for different databases
sqlit connection create --name "MySqlServer" --db-type mssql --server "localhost" --auth-type sql
sqlit connection create --name "MyPostgres" --db-type postgresql --server "localhost" --username "user" --password "pass"
sqlit connection create --name "MyMySQL" --db-type mysql --server "localhost" --username "user" --password "pass"
sqlit connection create --name "MyCockroach" --db-type cockroachdb --server "localhost" --port "26257" --database "defaultdb" --username "root"
sqlit connection create --name "MyLocalDB" --db-type sqlite --file-path "/path/to/database.db"

# Connect via SSH tunnel
sqlit connection create --name "RemoteDB" --db-type postgresql --server "db-host" --username "dbuser" --password "dbpass" \
  --ssh-enabled --ssh-host "ssh.example.com" --ssh-username "sshuser" --ssh-auth-type password --ssh-password "sshpass"

# Manage connections
sqlit connection list
sqlit connection delete "MyConnection"
```

## Keybindings

| Key | Action |
|-----|--------|
| `i` | Enter INSERT mode |
| `Esc` | Back to NORMAL mode |
| `e` / `q` / `r` | Focus Explorer / Query / Results |
| `s` | SELECT TOP 100 from table |
| `h` | Query history |
| `d` | Clear query |
| `n` | New query (clear all) |
| `Ctrl+P` | Command palette |
| `Ctrl+Q` | Quit |
| `?` | Help |

Autocomplete triggers automatically in INSERT mode. Use `Tab` to accept.

You can also receive autocompletion on columns by typing the table name and hitting "."

## Configuration

Connections and settings are stored in `~/.sqlit/`.

## Contributing

See `CONTRIBUTING.md` for development setup, testing, CI, and CockroachDB quickstart steps.

## License

MIT

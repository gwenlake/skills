# Gwenlake

Connects Claude to [Gwenlake Atlas](https://docs.gwenlake.com/atlas/) through the Gwenlake MCP server (`https://atlas.gwenlake.com/mcp`).

With it, Claude can search the catalog of your organization, describe and query datasets in SQL, read ontologies and their objects, search documents, ask Atlas agents, and follow builds and their lineage. Where your plan allows it, Claude can also create datasets, transforms and schedules.

## Install

```
/plugin install gwenlake --marketplace gwenlake/skills
```

## Sign in

The server signs you in with your Gwenlake account. In Claude Code, run `/mcp`, select `gwenlake` and choose `Authenticate`. No API key is involved: Claude sees what your account can see.

## Skills

The skills that teach an agent to build on Atlas (API, applications, ontologies) are a separate plugin, `gwenlake-skills`, in the [same repository](https://github.com/gwenlake/skills).

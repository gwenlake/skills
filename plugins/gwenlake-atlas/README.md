# Gwenlake

Connects Claude to [Gwenlake Atlas](https://docs.gwenlake.com/atlas/) through the Gwenlake MCP server (`https://atlas.gwenlake.com/mcp`).

With it, Claude can search the catalog of your organization, describe and query datasets in SQL, read ontologies and their objects, search documents, ask Atlas agents, and follow builds and their lineage. Where your plan allows it, Claude can also create datasets, transforms, schedules, ontologies and applications.

## Install

```
/plugin install gwenlake-atlas --marketplace gwenlake/skills
```

## Sign in

The server signs you in with your Gwenlake account. In Claude Code, run `/mcp`, select `gwenlake` and choose `Authenticate`. No API key is involved: Claude sees what your account can see.

## Skills

The plugin ships three skills that teach Claude how the server is meant to be used. Claude loads the one that matches your request; you can also call one by name.

| Skill | What it teaches |
| --- | --- |
| `/gwenlake-atlas:atlas` | Finding a resource, choosing between an agent, an ontology and SQL to answer a question, and the order in which a pipeline is built |
| `/gwenlake-atlas:atlas-ontologies` | Designing an ontology that matches the data of a project: profiling the tables in SQL, the format the platform accepts, object types, links and actions |
| `/gwenlake-atlas:atlas-applications` | Building, validating and publishing an Atlas application: the `app.yaml` format, the eighteen widgets, the layout |

The skills hold instructions and examples only. They run no script and need no API key: everything goes through the MCP server, with your account.

## Privacy

The server reads and writes the data of your Gwenlake account on your behalf. See the [Privacy policy](https://gwenlake.com/privacy/).

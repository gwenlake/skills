# Gwenlake for Claude

This repository holds the Claude plugin for [Gwenlake Atlas](https://docs.gwenlake.com/atlas/): the Gwenlake MCP server, and the skills that teach Claude how to use it.

- [./plugins/gwenlake](./plugins/gwenlake): the plugin
- [./template](./template): a starting point for a new skill

## What is in the plugin

**The MCP server** (`https://atlas.gwenlake.com/mcp`) signs you in with your Gwenlake account. Claude then sees what your account can see: it searches the catalog, queries datasets in SQL, reads ontologies and documents, asks agents and follows builds. Where your plan allows it, it also creates datasets, transforms, schedules, ontologies and applications.

**The skills** are folders of instructions and examples, in the [Agent Skills](https://agentskills.io) convention, that Claude loads when a task calls for them.

| Skill | What it teaches |
| --- | --- |
| [`atlas`](./plugins/gwenlake/skills/atlas) | Finding a resource, choosing between an agent, an ontology and SQL to answer a question, and the order in which a pipeline is built |
| [`atlas-ontologies`](./plugins/gwenlake/skills/atlas-ontologies) | Designing an ontology that matches the data of a project: profiling the tables in SQL, the format the platform accepts, object types, links and actions |
| [`atlas-applications`](./plugins/gwenlake/skills/atlas-applications) | Building, validating and publishing Atlas applications: the `app.yaml` format, the fifteen widgets, the layout |

The skills run no script and need no API key: everything goes through the MCP server.

## Install in Claude Code

```
/plugin install gwenlake --marketplace gwenlake/skills
```

Or register the marketplace with `/plugin marketplace add gwenlake/skills`, then select `Browse and install plugins`.

Then sign in: run `/mcp`, select `gwenlake` and choose `Authenticate`.

You do not have to name a skill: Claude loads the one that matches your request. Just ask for what you want:

| You ask | Skill loaded |
| --- | --- |
| "What was the revenue by region last quarter in the `sales` project?" | `atlas` |
| "Create the ontology of the `sales` project in Atlas" | `atlas-ontologies` |
| "Build an Atlas application over the `sales/orders` dataset, with a filter by region and the monthly revenue" | `atlas-applications` |

To be sure a given skill is used, name it in your request, or call it directly, for example `/gwenlake:atlas-ontologies`.

## Upgrading from version 1

Version 1 shipped a second plugin, `gwenlake-skills`, whose skills called the Atlas API with Python scripts and an API key. Version 2 replaces it: the skills now use the MCP server. Uninstall `gwenlake-skills` and install `gwenlake`. The `atlas-api` skill is gone; calling the API directly is documented at https://docs.gwenlake.com/atlas/.

## Disclaimer

**These skills are provided for demonstration and educational purposes only.** While they describe how Gwenlake Atlas works, the platform evolves, and the behavior you get from the platform or from an agent using these skills may differ from what is shown here. Always test skills thoroughly in your own environment before relying on them for critical tasks.

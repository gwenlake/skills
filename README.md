# Skills

Skills are folders of instructions, scripts and resources that an agent loads when a task calls for them. This repository holds the skills that teach agents how to build on [Gwenlake Atlas](https://docs.gwenlake.com/atlas/), so that a new agent does the work correctly without being told again how the platform works.

Each skill is self-contained in its own folder, with a `SKILL.md` file holding the metadata and the instructions, in the [Agent Skills](https://agentskills.io) convention.

## Disclaimer

**These skills are provided for demonstration and educational purposes only.** While they describe how Gwenlake Atlas works, the platform evolves, and the behavior you get from the platform or from an agent using these skills may differ from what is shown here. These skills are meant to illustrate patterns and possibilities. Always test skills thoroughly in your own environment before relying on them for critical tasks.

# Skill sets

- [./skills](./skills): the skills
- [./template](./template): a starting point for a new skill

| Skill | What it teaches |
| --- | --- |
| [`atlas-api`](./skills/atlas-api) | Calling the Atlas API over HTTP, from the `gwenlake` Python library or from the command line: authentication, datasets and files, SQL, builds and schedules, inference, agents. With a script that makes any call, runs SQL and uploads files |
| [`atlas-applications`](./skills/atlas-applications) | Building, validating and publishing Atlas applications: the `app.yaml` format, the fifteen widgets, the layout, the API. With a script that explores the data, validates and saves |
| [`atlas-ontologies`](./skills/atlas-ontologies) | Designing an ontology that matches the data of a project: the format the platform accepts, object types, links and actions. With a script that profiles the tables (schema, keys, values, references), drafts the ontology, checks it against the data and publishes it |

# Try in Claude Code, Claude.ai, and the API

## Claude Code

You can register this repository as a Claude Code Plugin marketplace by running the following command in Claude Code:

```
/plugin marketplace add gwenlake/skills
```

Then, to install the skills:

1. Select `Browse and install plugins`
2. Select `gwenlake`
3. Select `gwenlake-skills`
4. Select `Install now`

Alternatively, directly install the plugin via:

```
/plugin install gwenlake-skills@gwenlake
```

After installing the plugin, Claude Code needs an API key to reach your platform: set `GWENLAKE_API_KEY`, or create a profile in `~/.gwenlake/credentials`.

You do not have to name a skill: Claude loads the one that matches your request. Just ask for what you want:

| You ask | Skill loaded |
| --- | --- |
| "Create the ontology of the `sales` project in Atlas" | `atlas-ontologies` |
| "Build an Atlas application over the `sales/orders` dataset, with a filter by region and the monthly revenue" | `atlas-applications` |
| "Export the `sales.customers` dataset of Atlas to a Parquet file" | `atlas-api` |

To be sure a given skill is used, name it in your request: "Use the `atlas-ontologies` skill to create the ontology of the `sales` project", or call it directly with `/gwenlake-skills:atlas-ontologies`.

## Claude.ai

To use a skill from this repository in Claude.ai, zip its folder and upload it as a custom skill by following the instructions in [Using skills in Claude](https://support.claude.com/en/articles/12512180-using-skills-in-claude#h_a4222fa77b).

## Claude API

You can upload a skill of this repository through the Skills API. See the [Skills API Quickstart](https://docs.claude.com/en/api/skills-guide#creating-a-skill) for more.

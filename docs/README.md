# :outbox_tray: Deploying the extension to Liquibase AWS Marketplace

1. We manually update the `liquibase-secure` version in pom.xml
2. The below steps run on every Liquibase Secure release.
   a. The dependabot.yml file checks for new versions of dependencies for package-ecosystem: "docker" and creates a pull request to update the dependencies, specifically for new version of liquibase-secure docker .
   b. The workflow file `dependabot-pr-merge-docker-changes.yml` auto merges the dependabot PR containing the new Docker Secure version.
   c. The deploy-extension-to-marketplace.yml file runs and publishes the `test` extension to the Liquibase AWS Marketplace.

<!-- TODO: The following sections will be updated in ticket https://datical.atlassian.net/browse/DAT-20280:
- Deploying the extension to Liquibase AWS Marketplace
- Testing Marketplace listing
- How to test the liquibase commands with the Marketplace listing
- Deploy the actual listing after testing steps
-->

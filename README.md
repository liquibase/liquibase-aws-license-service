# Liquibase AWS License Service Extension

Extension which validates licenses using AWS License Manager

# :outbox_tray: Deploying the extension to Liquibase AWS Marketplace

1. The `extension-update-pom.yml` file updates the version of the extension in the `pom.xml file` whenever there is a **new Liquibase Release**. It listens to the `repository_dispatch` event called `oss-released-version` from the `liquibase/liquibase` repository and then runs the workflow specified in the `extension-update-pom.yml` file.
2. We release a new version of `liquibase-aws-license-service` only when it is required, as this is a PRO extension.
3. When there is a new `liquibase-aws-license-service` version release, the dependabot in LPM(liquibase package manager) repository creates a PR: example : https://github.com/liquibase/liquibase-package-manager/pull/430/files#diff-0b0a9d274bd84c7dbfff4680de10599cd0d96458b06b74a925b2bcd3e3fc2fadR15. We need to **manually** merge the PR. Make sure to review and merge the PR before proceeding.
4. The `dependabot.yml` file checks for new versions of dependencies for Docker and creates a pull request to update these dependencies, specifically for OSS.
5. After we **manually** merge the Dependabot PR containing the new Docker OSS version, the `deploy-extension-to-marketplace.yml` file runs and publishes the extension to the `Liquibase AWS Marketplace`.

# :hammer: How to test the liquibase commands with the Marketplace listing

1. We have a `LiquibaseAWSMP` AWS account where we have listed the extension in the AWS Marketplace.
2. All the QA's and Dev's should have access to this account.
3. We have AWS Fargate Cluster called `aws-mp-test-cluster` setup in this account where we can run the Liquibase commands.
4. Most of the liquibase commands should already be defined under `Task Definitions` section in the ECS Cluster.
5. All you do is navigate to `Tasks` tab, `Run New Task`, under `Family` select the task definition you want to run, and then click on `Create`.

   ![](./docs/image/task_tab.png)

   ![](./docs/image/run_task.png)

6. You can also run the task using the `aws-cli` command.
   ```bash
   aws ecs run-task --cluster aws-mp-test-cluster --task-definition update-liquibase
   ```
7. To check logs of the task, click on the task you just ran under `Tasks` tab. And then navigate to `Logs` tab.

   ![](./docs/image/running_task.png)

   ![](./docs/image/logs_tab.png)

8. To add more commands to test in the `aws-mp-test-cluster`, you can add them in the `Task Definitions` section.
9. Contact the DevOps team to get access to the `LiquibaseAWSMP` AWS account or any other help required.


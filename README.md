# Liquibase AWS License Service Extension
Extension which validates licenses using AWS License Manager

## Notes
- This extension expects access to AWS, using standard AWS credentials mechanisms. Devs would need to get access to the following AWS account and set credentials from it: `LiquibaseAWSMP | 804611071420 | awsmp@liquibase.com`
- This extension leverages a vulnerability in the `LicenseServiceFactory` in OSS/Pro. If that vulnerability is fixed, then this extension will no longer work. More info available [here](https://datical.atlassian.net/browse/DAT-12399).
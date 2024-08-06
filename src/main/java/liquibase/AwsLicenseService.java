package liquibase;

import com.datical.liquibase.ext.logging.custommdc.Cache;
import liquibase.exception.UnexpectedLiquibaseException;
import liquibase.integration.IntegrationDetails;
import liquibase.license.LicenseInfo;
import liquibase.license.LicenseInstallResult;
import liquibase.license.LicenseService;
import liquibase.license.Location;
import liquibase.license.pro.DaticalTrueLicenseService;
import liquibase.license.pro.LicenseTier;
import liquibase.util.LiquibaseUtil;
import software.amazon.awssdk.auth.credentials.DefaultCredentialsProvider;
import software.amazon.awssdk.services.licensemanager.LicenseManagerClient;
import software.amazon.awssdk.services.licensemanager.model.*;

import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.TimeZone;
import java.util.UUID;

import static liquibase.license.pro.DaticalTrueLicenseService.LIQUIBASE_OPEN_SOURCE_MSG;

public class AwsLicenseService implements LicenseService {

    private boolean errorMessageHasBeenDisplayed = false;

    private static final Cache<CheckoutLicenseResponse> lazyLoader = new Cache<>(() -> {
        try (LicenseManagerClient client = LicenseManagerClient.builder()
                .credentialsProvider(DefaultCredentialsProvider.create()).build()) {

            CheckoutLicenseResponse checkoutLicenseResponse = client.checkoutLicense(
                    CheckoutLicenseRequest.builder()
                            .productSKU("prod-4ur64cg6hhkw2")
                            .checkoutType(CheckoutType.PROVISIONAL)
                            .keyFingerprint("aws:294406891311:AWS/Marketplace:issuer-fingerprint")
                            .entitlements(EntitlementData.builder()
                                    .name("datastore_targets")
                                    // This code below essentially says, "validate that I have a license for 1 DB target".
                                    .unit(EntitlementDataUnit.COUNT)
                                    .value("1")
                                    .build())
                            .clientToken(UUID.randomUUID().toString())
                            .build());

            CheckInLicenseResponse checkInLicenseResponse = client.checkInLicense(
                    CheckInLicenseRequest.builder()
                            .licenseConsumptionToken(checkoutLicenseResponse.licenseConsumptionToken())
                            .build()
            );

            if (!checkInLicenseResponse.sdkHttpResponse().isSuccessful()) {
                Scope.getCurrentScope().getLog(AwsLicenseService.class).warning("Failed to check license back in. License will remain checked out until its TTL expires. " + checkInLicenseResponse.sdkHttpResponse().statusCode() + " " + checkInLicenseResponse.sdkHttpResponse().statusText().orElse(""));
            }

            return checkoutLicenseResponse;
        }

    }, true);

    private static final String BUILD_VERSION = LiquibaseUtil.getBuildVersionInfo();

    @Override
    public int getPriority() {
        return Integer.MAX_VALUE;
    }

    @Override
    public boolean licenseIsInstalled() {
        // this is only called from within DaticalTrueLicenseService
        return lazyLoader.isGenerated();
    }

    @Override
    public boolean licenseIsValid(String s) {
        String fallbackMessage = "Falling back to Liquibase open source.";
        CheckoutLicenseResponse license = null;
        try {
            license = lazyLoader.get();
        } catch (NoEntitlementsAllowedException neae) {
            logErrorOnlyOnce(String.format("The AWS License check failed with no entitlements. %s%nError details: %s",
                    fallbackMessage,  neae.getMessage()), null);
            return false;
        } catch (Exception e) {
            logErrorOnlyOnce("The AWS License check failed with an unexpected exception. " + fallbackMessage, e);
            return false;
        }
        return license.hasEntitlementsAllowed();
    }

    private void logErrorOnlyOnce(String message, Exception e) {
        if (!errorMessageHasBeenDisplayed && Scope.getCurrentScope().get("integrationDetails", IntegrationDetails.class) != null) {
            Scope.getCurrentScope().getLog(getClass()).warning(message, e);
            errorMessageHasBeenDisplayed = true;
        }
    }

    @Override
    public String getLicenseInfo() {
        if (licenseIsValid(LicenseTier.PRO.getSubject())) {
            return "Liquibase Pro " + BUILD_VERSION + " (licensed through AWS License Manager)";
        } else {
            return String.format(LIQUIBASE_OPEN_SOURCE_MSG, BUILD_VERSION);
        }
    }

    @Override
    public LicenseInfo getLicenseInfoObject() {
        return new LicenseInfo(null, getExpirationDate());
    }

    @Override
    public LicenseInstallResult installLicense(Location... locations) {
        return new LicenseInstallResult(0, "Installing licenses is not supported by the AWS License Service.");
    }

    @Override
    public void disable() {
        // not supported
    }

    @Override
    public boolean licenseIsAboutToExpire() {
        // todo there is no way to determine this from AWS
        return false;
    }

    @Override
    public int daysTilExpiration() {
        // todo this is always going to return 0, because the license expiration date shows as 60 minutes from now
        return DaticalTrueLicenseService.daysDifference(getDate());
    }

    private Date getDate() {
        String end = null;
        try {
            end = lazyLoader.get().expiration();
        } catch (Exception e) {
            Scope.getCurrentScope().getLog(getClass()).warning("Failed to determine expiration date of AWS License.", e);
        }

        // If the end date is null, presume that the license is not valid from AWS, and thus, assume it expires right now.
        if (end == null) {
            return new Date();
        }

        // Parse it since it's a string for some reason
        SimpleDateFormat dateFormat = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss");
        dateFormat.setTimeZone(TimeZone.getTimeZone("UTC"));
        Date endDate = null;
        try {
            endDate = dateFormat.parse(end);
        } catch (ParseException e) {
            throw new UnexpectedLiquibaseException(e);
        }
        return endDate;
    }

    @Override
    public void reset() {
        lazyLoader.clearCache();
    }
}

package liquibase;

import liquibase.license.LicenseInfo;
import liquibase.license.LicenseInstallResult;
import liquibase.license.LicenseService;
import liquibase.license.Location;
import com.datical.liquibase.ext.logging.custommdc.Cache;
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
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;

import static liquibase.license.pro.DaticalTrueLicenseService.LIQUIBASE_OPEN_SOURCE_MSG;

public class AwsLicenseService implements LicenseService {

    private final static Cache<CheckoutLicenseResponse> lazyLoader = new Cache<>(() -> {
        try (LicenseManagerClient client = LicenseManagerClient.builder()
                .credentialsProvider(DefaultCredentialsProvider.create()).build()) {

            CheckoutLicenseResponse checkoutLicenseResponse = client.checkoutLicense(
                    CheckoutLicenseRequest.builder()
                            .productSKU("prod-hlrud2qqsxrgq")
                            .checkoutType(CheckoutType.PROVISIONAL)
                            .keyFingerprint("aws:294406891311:AWS/Marketplace:issuer-fingerprint")
                            .entitlements(EntitlementData.builder()
                                    .name("datastore_targets")
                                    .unit(EntitlementDataUnit.NONE)
                                    .build())
                            .clientToken(UUID.randomUUID().toString())
                            .build());

            try {
                TimeUnit.SECONDS.sleep(1);
            } catch (InterruptedException e) {
                throw new RuntimeException(e);
            }

            CheckInLicenseResponse checkInLicenseResponse = client.checkInLicense(
                    CheckInLicenseRequest.builder()
                            .licenseConsumptionToken(checkoutLicenseResponse.licenseConsumptionToken())
                            .build()
            );

            return checkoutLicenseResponse;
        }

    }, true);

    private final static String buildVersion = LiquibaseUtil.getBuildVersionInfo();

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
        String fallbackMessage = "Falling back to checking for a standard Liquibase Pro license.";
        CheckoutLicenseResponse license = null;
        try {
            license = lazyLoader.get();
        } catch (NoEntitlementsAllowedException neae) {
            Scope.getCurrentScope().getLog(getClass()).warning("The AWS License check failed with no entitlements. " + fallbackMessage, neae);
            return false;
        } catch (Exception e) {
            Scope.getCurrentScope().getLog(getClass()).warning("The AWS License check failed with an unexpected exception. " + fallbackMessage, e);
            return false;
        }
        return license.hasEntitlementsAllowed();
    }

    @Override
    public String getLicenseInfo() {
        if (licenseIsValid(LicenseTier.PRO.getSubject())) {
            return "Liquibase Pro " + buildVersion + " (licensed through AWS License Manager)";
        } else {
            return String.format(LIQUIBASE_OPEN_SOURCE_MSG, buildVersion);
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
            throw new RuntimeException(e);
        }
        return endDate;
    }

    @Override
    public void reset() {
        lazyLoader.clearCache();
    }

    @Override
    public Date getExpirationDate() {
        return getDate();
    }
}

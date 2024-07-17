package liquibase

import org.junit.jupiter.api.Test

import static org.junit.jupiter.api.Assertions.assertEquals

class AwsLicenseServiceTest {

    @Test
    void getPriority_returnsMaxInteger() {
        assertEquals(Integer.MAX_VALUE, new AwsLicenseService().getPriority())
    }
}

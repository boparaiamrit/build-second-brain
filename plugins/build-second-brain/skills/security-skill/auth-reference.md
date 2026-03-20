# Auth Reference — JWT, Sessions, SSO, RBAC/ABAC, Impersonation, Account Security, API Keys

> Read this file when implementing authentication flows, authorization logic, session management,
> SSO integration, admin impersonation, password policies, or API key authentication.

---

## Table of Contents
1. [JWT Lifecycle Management](#jwt-lifecycle-management)
2. [Session Management](#session-management)
3. [SSO Integration Security](#sso-integration-security)
4. [RBAC/ABAC with CASL](#rbacabac-with-casl)
5. [Admin Impersonation Security](#admin-impersonation-security)
6. [Account Security](#account-security)
7. [API Key Authentication](#api-key-authentication)
8. [Multi-Tenant Auth Patterns](#multi-tenant-auth-patterns)

---

## JWT Lifecycle Management

### Token Pair Pattern

| Token | Type | Lifetime | Storage | Purpose |
|-------|------|----------|---------|---------|
| Access token | JWT (signed) | 15 minutes | HttpOnly Secure SameSite=Strict cookie | Authenticates API requests |
| Refresh token | Opaque (random 64 bytes) | 7 days | HttpOnly Secure SameSite=Strict cookie + hashed in DB | Issues new access tokens |

**Never store tokens in localStorage or sessionStorage.** XSS can read them. Cookies with HttpOnly are immune to JS access.

### Access Token Claims Structure

```typescript
interface AccessTokenPayload {
  // Identity
  sub: string;              // userId (UUID)
  email: string;            // user email (for logging, not for auth decisions)

  // Tenant scope
  companyId: string;        // billing entity
  workspaceId: string;      // current workspace (changes on workspace switch)
  domainId?: string;        // set if user is domain-scoped

  // Authorization
  role: 'company_owner' | 'company_admin' | 'workspace_admin' | 'user';
  permissions?: string[];   // custom permissions for MSSP dynamic roles (UC3)

  // Security flags
  mfa: boolean;             // true if MFA was completed in this session
  sso: boolean;             // true if authenticated via SSO (not password)
  isImpersonated: boolean;  // true if admin is impersonating this user
  impersonatorId?: string;  // original admin userId (set only when isImpersonated=true)

  // Token metadata
  iat: number;              // issued at (Unix seconds)
  exp: number;              // expires at (Unix seconds) — iat + 900 (15 min)
  jti: string;              // unique token ID (UUID) — for revocation blacklist
  iss: string;              // issuer — your app domain
  aud: string;              // audience — 'api' or 'admin'

  // Subscription context (avoids DB lookup on every request)
  tier: 'free' | 'pro' | 'business' | 'enterprise';
}
```

### Token Generation

```typescript
@Injectable()
export class TokenService {
  constructor(
    private readonly jwtService: JwtService,
    @Inject('REDIS') private readonly redis: Redis,
    @Inject(DB_TOKEN) private readonly db: DB,
  ) {}

  async generateTokenPair(user: AuthenticatedUser, workspaceId: string): Promise<TokenPair> {
    const workspace = await this.db.query.workspaces.findFirst({
      where: eq(workspaces.id, workspaceId),
      with: { company: true },
    });
    if (!workspace) throw new NotFoundException('Workspace not found');

    const jti = randomUUID();

    const accessToken = this.jwtService.sign(
      {
        sub: user.id,
        email: user.email,
        companyId: workspace.companyId,
        workspaceId: workspace.id,
        role: user.role,
        mfa: user.mfaVerified ?? false,
        sso: user.ssoAuthenticated ?? false,
        isImpersonated: false,
        tier: workspace.company.subscriptionTier,
        jti,
        aud: 'api',
      },
      { expiresIn: '15m', algorithm: 'RS256' },
    );

    const refreshToken = randomBytes(64).toString('base64url');
    const refreshTokenHash = createHash('sha256').update(refreshToken).digest('hex');

    // Store refresh token hash in DB — enables per-device revocation
    await this.db.insert(refreshTokens).values({
      userId: user.id,
      tokenHash: refreshTokenHash,
      workspaceId: workspace.id,
      deviceFingerprint: user.deviceFingerprint,
      expiresAt: addDays(new Date(), 7),
    });

    return { accessToken, refreshToken };
  }
}
```

### Token Refresh Flow (With Race Condition Handling)

When the access token expires, the client sends the refresh token to get a new pair. Concurrent tabs can race on this endpoint.

```typescript
@Controller('auth')
export class AuthController {
  @Post('refresh')
  @UseGuards(RefreshTokenGuard) // validates cookie exists, not expired
  async refresh(
    @Req() req: Request,
    @Res({ passthrough: true }) res: Response,
  ): Promise<{ accessToken: string }> {
    const refreshToken = req.cookies['refresh_token'];
    const tokenHash = createHash('sha256').update(refreshToken).digest('hex');

    // Atomic lock — prevents race condition when multiple tabs refresh simultaneously
    const lockKey = `refresh-lock:${tokenHash}`;
    const lockAcquired = await this.redis.set(lockKey, '1', 'EX', 10, 'NX');

    if (!lockAcquired) {
      // Another request is already refreshing — wait for the result
      const cachedResult = await this.waitForRefreshResult(tokenHash, 5000);
      if (cachedResult) {
        this.setTokenCookies(res, cachedResult);
        return { accessToken: cachedResult.accessToken };
      }
      throw new UnauthorizedException('Refresh in progress, retry');
    }

    try {
      // Validate refresh token exists and is not revoked
      const storedToken = await this.db.query.refreshTokens.findFirst({
        where: and(
          eq(refreshTokens.tokenHash, tokenHash),
          gt(refreshTokens.expiresAt, new Date()),
          isNull(refreshTokens.revokedAt),
        ),
      });
      if (!storedToken) throw new UnauthorizedException('Invalid refresh token');

      // Rotate: revoke old, issue new
      await this.db.update(refreshTokens)
        .set({ revokedAt: new Date(), replacedByHash: null }) // will set after new token
        .where(eq(refreshTokens.id, storedToken.id));

      const user = await this.userService.findById(storedToken.userId);
      const tokenPair = await this.tokenService.generateTokenPair(user, storedToken.workspaceId);

      // Link old token to new for audit trail
      const newHash = createHash('sha256').update(tokenPair.refreshToken).digest('hex');
      await this.db.update(refreshTokens)
        .set({ replacedByHash: newHash })
        .where(eq(refreshTokens.id, storedToken.id));

      // Cache result for concurrent requests hitting the lock
      await this.redis.set(
        `refresh-result:${tokenHash}`,
        JSON.stringify(tokenPair),
        'EX', 10,
      );

      this.setTokenCookies(res, tokenPair);
      return { accessToken: tokenPair.accessToken };
    } finally {
      await this.redis.del(lockKey);
    }
  }

  private async waitForRefreshResult(tokenHash: string, timeoutMs: number): Promise<TokenPair | null> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const raw = await this.redis.get(`refresh-result:${tokenHash}`);
      if (raw) return JSON.parse(raw);
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    return null;
  }

  private setTokenCookies(res: Response, tokens: TokenPair): void {
    res.cookie('access_token', tokens.accessToken, {
      httpOnly: true, secure: true, sameSite: 'strict',
      maxAge: 15 * 60 * 1000, // 15 minutes
      path: '/',
    });
    res.cookie('refresh_token', tokens.refreshToken, {
      httpOnly: true, secure: true, sameSite: 'strict',
      maxAge: 7 * 24 * 60 * 60 * 1000, // 7 days
      path: '/auth/refresh', // only sent to refresh endpoint
    });
  }
}
```

### Token Revocation Strategy

| Token Type | Revocation Method | Lookup Speed | Use Case |
|------------|-------------------|--------------|----------|
| Access token | Redis blacklist (`blacklist:jti:{jti}`) with TTL = remaining token lifetime | O(1) | Immediate logout, compromised token |
| Refresh token | DB column `revokedAt` set to NOW() | O(1) by hash index | Password change, device revocation |
| All user tokens | Redis: `SET user-revoked:{userId} {timestamp}` — reject any access token with `iat < timestamp` | O(1) | Password change, account suspension |

```typescript
// Revoke a single access token (immediate logout)
async revokeAccessToken(jti: string, expiresAt: number): Promise<void> {
  const ttl = expiresAt - Math.floor(Date.now() / 1000);
  if (ttl > 0) {
    await this.redis.set(`blacklist:jti:${jti}`, '1', 'EX', ttl);
  }
}

// Revoke ALL tokens for a user (password change, account lock)
async revokeAllUserTokens(userId: string): Promise<void> {
  // Blacklist all current access tokens
  await this.redis.set(`user-revoked:${userId}`, Math.floor(Date.now() / 1000).toString());

  // Revoke all refresh tokens in DB
  await this.db.update(refreshTokens)
    .set({ revokedAt: new Date() })
    .where(and(
      eq(refreshTokens.userId, userId),
      isNull(refreshTokens.revokedAt),
    ));
}
```

### JwtStrategy (NestJS Passport)

```typescript
@Injectable()
export class JwtStrategy extends PassportStrategy(Strategy, 'jwt') {
  constructor(
    @Inject('REDIS') private readonly redis: Redis,
    configService: ConfigService,
  ) {
    super({
      jwtFromRequest: ExtractJwt.fromExtractors([
        (req: Request) => req.cookies?.['access_token'] ?? null,
      ]),
      ignoreExpiration: false,
      secretOrKeyProvider: async (_req, _token, done) => {
        // Support key rotation: try current key, fall back to previous
        const currentKey = configService.get<string>('JWT_PUBLIC_KEY');
        done(null, currentKey);
      },
      algorithms: ['RS256'],
      audience: 'api',
      issuer: configService.get<string>('JWT_ISSUER'),
    });
  }

  async validate(payload: AccessTokenPayload): Promise<AccessTokenPayload> {
    // Check single-token blacklist
    const isBlacklisted = await this.redis.exists(`blacklist:jti:${payload.jti}`);
    if (isBlacklisted) throw new UnauthorizedException('Token revoked');

    // Check user-level revocation (password change, account lock)
    const userRevokedAt = await this.redis.get(`user-revoked:${payload.sub}`);
    if (userRevokedAt && payload.iat < parseInt(userRevokedAt, 10)) {
      throw new UnauthorizedException('Session invalidated');
    }

    return payload;
  }
}
```

### RSA Key Rotation (Zero-Downtime)

| Phase | Duration | What Happens |
|-------|----------|-------------|
| 1. Generate new key pair | Instant | New RSA-2048 key pair generated, stored in secrets manager |
| 2. Dual-accept period | 24 hours | JwtStrategy accepts signatures from BOTH old and new public keys |
| 3. Switch signing key | Instant | TokenService starts signing with new private key |
| 4. Drain period | 15 minutes | Wait for all existing access tokens signed with old key to expire |
| 5. Remove old key | After drain | Old public key removed from verification set |

```typescript
// Key rotation: secretOrKeyProvider accepts both keys during rotation
secretOrKeyProvider: async (_req, rawToken, done) => {
  const decodedHeader = JSON.parse(
    Buffer.from(rawToken.split('.')[0], 'base64url').toString(),
  );
  const kid = decodedHeader.kid; // key ID in JWT header
  const key = await this.keyStore.getPublicKey(kid); // returns current or previous
  if (!key) return done(new UnauthorizedException('Unknown signing key'));
  done(null, key);
},
```

---

## Session Management

### Redis Session Storage Structure

```
session:{userId}:{deviceFingerprint}
  -> JSON { userId, workspaceId, role, mfa, sso, isImpersonated, createdAt, lastActivityAt, ip, userAgent }
  -> TTL: 30 minutes (sliding window — extended on each validated request)

session-index:{userId}
  -> SET of deviceFingerprints (for listing all active sessions)

session-count:{companyId}
  -> INT (atomic counter for concurrent session limits)
```

```typescript
interface SessionData {
  userId: string;
  workspaceId: string;
  companyId: string;
  role: string;
  mfa: boolean;
  sso: boolean;
  isImpersonated: boolean;
  impersonatorId?: string;
  createdAt: number;         // Unix ms
  lastActivityAt: number;    // Unix ms — updated on each request
  ip: string;
  userAgent: string;
  deviceFingerprint: string;
}
```

### Session Service

```typescript
@Injectable()
export class SessionService {
  private readonly SESSION_TTL = 1800;        // 30 minutes sliding window
  private readonly MAX_SESSION_AGE = 86400;   // 24 hours absolute max

  constructor(@Inject('REDIS') private readonly redis: Redis) {}

  // --- CREATE ---
  async createSession(data: SessionData, planLimits: PlanLimits): Promise<string> {
    // Session fixation prevention: always generate new fingerprint on login
    const fingerprint = randomBytes(32).toString('hex');
    data.deviceFingerprint = fingerprint;
    data.createdAt = Date.now();
    data.lastActivityAt = Date.now();

    // Check concurrent session limit
    const activeSessions = await this.redis.scard(`session-index:${data.userId}`);
    if (activeSessions >= planLimits.maxConcurrentSessions) {
      // Evict oldest session
      const oldestFingerprint = await this.findOldestSession(data.userId);
      if (oldestFingerprint) await this.invalidateSession(data.userId, oldestFingerprint);
    }

    const sessionKey = `session:${data.userId}:${fingerprint}`;
    await this.redis.setex(sessionKey, this.SESSION_TTL, JSON.stringify(data));
    await this.redis.sadd(`session-index:${data.userId}`, fingerprint);

    return fingerprint;
  }

  // --- VALIDATE (called on every request by session middleware) ---
  async validateSession(userId: string, fingerprint: string): Promise<SessionData | null> {
    const sessionKey = `session:${userId}:${fingerprint}`;
    const raw = await this.redis.get(sessionKey);
    if (!raw) return null;

    const session: SessionData = JSON.parse(raw);

    // Absolute expiry check — session cannot exceed MAX_SESSION_AGE regardless of activity
    if (Date.now() - session.createdAt > this.MAX_SESSION_AGE * 1000) {
      await this.invalidateSession(userId, fingerprint);
      return null;
    }

    // Sliding window: extend TTL on each valid request
    session.lastActivityAt = Date.now();
    await this.redis.setex(sessionKey, this.SESSION_TTL, JSON.stringify(session));

    return session;
  }

  // --- EXTEND (workspace switch — new session data, same fingerprint) ---
  async extendSession(userId: string, fingerprint: string, updates: Partial<SessionData>): Promise<void> {
    const sessionKey = `session:${userId}:${fingerprint}`;
    const raw = await this.redis.get(sessionKey);
    if (!raw) throw new UnauthorizedException('Session not found');

    const session: SessionData = { ...JSON.parse(raw), ...updates, lastActivityAt: Date.now() };
    await this.redis.setex(sessionKey, this.SESSION_TTL, JSON.stringify(session));
  }

  // --- LIST (multi-device management UI) ---
  async listActiveSessions(userId: string): Promise<SessionSummary[]> {
    const fingerprints = await this.redis.smembers(`session-index:${userId}`);
    const sessions: SessionSummary[] = [];

    for (const fp of fingerprints) {
      const raw = await this.redis.get(`session:${userId}:${fp}`);
      if (!raw) {
        // Stale index entry — clean up
        await this.redis.srem(`session-index:${userId}`, fp);
        continue;
      }
      const session: SessionData = JSON.parse(raw);
      sessions.push({
        deviceFingerprint: fp,
        ip: session.ip,
        userAgent: session.userAgent,
        createdAt: session.createdAt,
        lastActivityAt: session.lastActivityAt,
        isCurrent: false, // caller sets this based on request fingerprint
      });
    }

    return sessions.sort((a, b) => b.lastActivityAt - a.lastActivityAt);
  }

  // --- INVALIDATE SINGLE (revoke one device) ---
  async invalidateSession(userId: string, fingerprint: string): Promise<void> {
    await this.redis.del(`session:${userId}:${fingerprint}`);
    await this.redis.srem(`session-index:${userId}`, fingerprint);
  }

  // --- INVALIDATE ALL (password change, account lock) ---
  async invalidateAllSessions(userId: string): Promise<void> {
    const fingerprints = await this.redis.smembers(`session-index:${userId}`);
    if (fingerprints.length > 0) {
      const keys = fingerprints.map(fp => `session:${userId}:${fp}`);
      await this.redis.del(...keys);
    }
    await this.redis.del(`session-index:${userId}`);
  }

  private async findOldestSession(userId: string): Promise<string | null> {
    const fingerprints = await this.redis.smembers(`session-index:${userId}`);
    let oldest: { fp: string; lastActivity: number } | null = null;

    for (const fp of fingerprints) {
      const raw = await this.redis.get(`session:${userId}:${fp}`);
      if (!raw) continue;
      const session: SessionData = JSON.parse(raw);
      if (!oldest || session.lastActivityAt < oldest.lastActivity) {
        oldest = { fp, lastActivity: session.lastActivityAt };
      }
    }

    return oldest?.fp ?? null;
  }
}
```

### Concurrent Session Limits by Plan

| Plan | Max Concurrent Sessions Per User | Max Concurrent Sessions Per Company |
|------|----------------------------------|-------------------------------------|
| Free | 2 | 10 |
| Pro | 5 | 50 |
| Business | 10 | 200 |
| Enterprise | Unlimited | Unlimited |

---

## SSO Integration Security

### SAML Assertion Validation Checklist

Every SAML response MUST pass ALL of these checks before the user is authenticated. Failure on any single check rejects the assertion.

| # | Check | What to Validate | Attack Prevented |
|---|-------|------------------|------------------|
| 1 | **Signature validity** | XML signature verifies against IdP's public certificate | Assertion forgery |
| 2 | **Signature covers assertion** | Signature reference URI matches the Assertion ID (not just the Response) | Assertion wrapping attack |
| 3 | **Audience restriction** | `<AudienceRestriction>` contains your SP entity ID | Cross-service assertion replay |
| 4 | **Recipient URL** | `<SubjectConfirmationData Recipient>` matches your ACS URL exactly | Assertion redirect attack |
| 5 | **NotBefore / NotOnOrAfter** | Current time is within the validity window (allow 5-minute clock skew max) | Replay attack with expired assertion |
| 6 | **InResponseTo** | Matches the AuthnRequest ID you sent (stored in Redis with 10-min TTL) | Unsolicited assertion injection |
| 7 | **Issuer** | `<Issuer>` matches the expected IdP entity ID for this workspace's SSO connection | IdP spoofing |
| 8 | **NameID present** | `<NameID>` is present and non-empty | Incomplete assertion |
| 9 | **Destination** | `<Response Destination>` matches your ACS URL | Response redirect attack |
| 10 | **No duplicate assertion** | Assertion ID has not been seen before (check Redis set with TTL matching NotOnOrAfter) | Replay attack |
| 11 | **No XML signature wrapping** | Only one `<Assertion>` element exists in the response | XML signature wrapping |
| 12 | **Certificate pinning** | IdP certificate fingerprint matches stored fingerprint (not just any valid cert) | Certificate substitution |

### SAML Callback Handler

```typescript
@Controller('auth/sso')
export class SsoCallbackController {
  @Post('saml/callback')
  async samlCallback(
    @Body('SAMLResponse') samlResponseB64: string,
    @Body('RelayState') relayState: string,
    @Res() res: Response,
  ): Promise<void> {
    // 1. Decode and parse the SAML response
    const samlXml = Buffer.from(samlResponseB64, 'base64').toString('utf-8');

    // 2. Extract workspace from RelayState (encrypted, not plaintext workspace ID)
    const { workspaceId, nonce } = this.decryptRelayState(relayState);

    // 3. Load SSO connection for this workspace
    const ssoConnection = await this.ssoRepo.findActiveByWorkspace(workspaceId);
    if (!ssoConnection) throw new UnauthorizedException('SSO not configured for this workspace');

    // 4. Validate SAML assertion (all 12 checks above)
    const assertion = await this.samlValidator.validate(samlXml, {
      idpCert: ssoConnection.idpCertificate,
      idpEntityId: ssoConnection.idpEntityId,
      spEntityId: this.configService.get('SAML_SP_ENTITY_ID'),
      acsUrl: this.configService.get('SAML_ACS_URL'),
      expectedRequestId: await this.redis.get(`saml-request:${nonce}`),
      maxClockSkewSeconds: 300,
    });

    // 5. Prevent replay — mark assertion ID as consumed
    const assertionTtl = Math.ceil((assertion.notOnOrAfter.getTime() - Date.now()) / 1000) + 60;
    const wasNew = await this.redis.set(
      `saml-assertion:${assertion.assertionId}`, '1', 'EX', assertionTtl, 'NX',
    );
    if (!wasNew) throw new UnauthorizedException('SAML assertion already used');

    // 6. Clean up the request ID
    await this.redis.del(`saml-request:${nonce}`);

    // 7. Just-in-time provisioning or lookup
    const user = await this.ssoUserService.findOrProvision({
      email: assertion.nameId,
      firstName: assertion.attributes.firstName,
      lastName: assertion.attributes.lastName,
      groups: assertion.attributes.groups ?? [],
      workspaceId,
      companyId: ssoConnection.companyId,
    });

    // 8. Issue tokens and redirect
    const tokenPair = await this.tokenService.generateTokenPair(
      { ...user, ssoAuthenticated: true, mfaVerified: true }, // SSO counts as MFA
      workspaceId,
    );
    this.setTokenCookies(res, tokenPair);
    res.redirect(302, `${this.configService.get('FRONTEND_URL')}/dashboard`);
  }
}
```

### OAuth2/OIDC Flow with PKCE

PKCE (Proof Key for Code Exchange) is mandatory for all OAuth flows. Never use the implicit grant.

```typescript
@Injectable()
export class OAuthService {
  // Step 1: Generate authorization URL with PKCE
  async initiateOAuth(workspaceId: string, provider: string): Promise<{ authUrl: string }> {
    const ssoConnection = await this.ssoRepo.findActive(workspaceId, provider);
    if (!ssoConnection) throw new NotFoundException('SSO connection not found');

    // PKCE: generate code verifier and challenge
    const codeVerifier = randomBytes(64).toString('base64url'); // 43-128 chars
    const codeChallenge = createHash('sha256').update(codeVerifier).digest('base64url');

    // Anti-CSRF: state parameter binds request to session
    const state = randomBytes(32).toString('hex');

    // Store PKCE verifier + state in Redis (10-minute TTL)
    await this.redis.setex(`oauth-state:${state}`, 600, JSON.stringify({
      workspaceId,
      provider,
      codeVerifier,
      createdAt: Date.now(),
    }));

    const params = new URLSearchParams({
      client_id: ssoConnection.clientId,
      redirect_uri: this.configService.get('OAUTH_REDIRECT_URI'),
      response_type: 'code',
      scope: 'openid email profile',
      state,
      code_challenge: codeChallenge,
      code_challenge_method: 'S256',
      nonce: randomBytes(16).toString('hex'),
    });

    const authUrl = `${ssoConnection.authorizationUrl}?${params.toString()}`;
    return { authUrl };
  }

  // Step 2: Handle callback — validate state, exchange code
  async handleCallback(code: string, state: string): Promise<TokenPair> {
    // Validate state parameter — prevents CSRF
    const raw = await this.redis.get(`oauth-state:${state}`);
    if (!raw) throw new UnauthorizedException('Invalid or expired OAuth state');

    const stateData = JSON.parse(raw);
    await this.redis.del(`oauth-state:${state}`); // Single-use

    const ssoConnection = await this.ssoRepo.findActive(stateData.workspaceId, stateData.provider);

    // Exchange authorization code for tokens (with PKCE verifier)
    const tokenResponse = await this.httpService.axiosRef.post(
      ssoConnection.tokenUrl,
      new URLSearchParams({
        grant_type: 'authorization_code',
        code,
        redirect_uri: this.configService.get('OAUTH_REDIRECT_URI'),
        client_id: ssoConnection.clientId,
        client_secret: ssoConnection.clientSecret, // confidential client
        code_verifier: stateData.codeVerifier,
      }).toString(),
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } },
    );

    // Validate ID token (OIDC)
    const idToken = tokenResponse.data.id_token;
    const claims = await this.validateIdToken(idToken, ssoConnection);

    // JIT provisioning
    const user = await this.ssoUserService.findOrProvision({
      email: claims.email,
      firstName: claims.given_name,
      lastName: claims.family_name,
      workspaceId: stateData.workspaceId,
      companyId: ssoConnection.companyId,
    });

    return this.tokenService.generateTokenPair(
      { ...user, ssoAuthenticated: true, mfaVerified: true },
      stateData.workspaceId,
    );
  }

  private async validateIdToken(idToken: string, connection: SsoConnection): Promise<OidcClaims> {
    const jwksClient = jwks({ jwksUri: connection.jwksUri, cache: true, rateLimit: true });
    const decoded = jwt.decode(idToken, { complete: true });
    if (!decoded) throw new UnauthorizedException('Invalid ID token');

    const signingKey = await jwksClient.getSigningKey(decoded.header.kid);
    const verified = jwt.verify(idToken, signingKey.getPublicKey(), {
      audience: connection.clientId,
      issuer: connection.issuerUrl,
      algorithms: ['RS256'],
    }) as OidcClaims;

    // Verify nonce if stored (prevents replay)
    return verified;
  }
}
```

### IdP-Initiated vs SP-Initiated SSO

| Flow | Who Starts | Security Posture | Recommendation |
|------|-----------|------------------|----------------|
| SP-initiated | User clicks "Login with SSO" in your app | Higher — you control the AuthnRequest, InResponseTo validates | Preferred |
| IdP-initiated | User clicks your app tile in their IdP portal | Lower — no AuthnRequest to validate against, InResponseTo is absent | Support but add extra validation |

**IdP-initiated additional controls:**

```typescript
// For IdP-initiated SAML (no AuthnRequest was sent)
if (!assertion.inResponseTo) {
  // Extra validation since we didn't initiate this flow:
  // 1. Tighter time window (2 minutes instead of 5)
  const age = Date.now() - assertion.issueInstant.getTime();
  if (age > 120_000) throw new UnauthorizedException('IdP-initiated assertion too old');

  // 2. Must have RelayState with encrypted workspace binding
  if (!relayState) throw new UnauthorizedException('RelayState required for IdP-initiated SSO');

  // 3. Rate limit per IdP (prevent assertion flooding)
  const rateKey = `idp-initiated:${ssoConnection.id}`;
  const count = await this.redis.incr(rateKey);
  if (count === 1) await this.redis.expire(rateKey, 60);
  if (count > 20) throw new TooManyRequestsException('IdP-initiated SSO rate limit');
}
```

### Just-In-Time User Provisioning

```typescript
@Injectable()
export class SsoUserService {
  async findOrProvision(ssoData: SsoUserData): Promise<User> {
    // Look up by email within the workspace
    let user = await this.userRepo.findByEmailInWorkspace(ssoData.email, ssoData.workspaceId);

    if (user) {
      // Update profile from IdP attributes (name changes, group changes)
      await this.userRepo.update(user.id, {
        firstName: ssoData.firstName,
        lastName: ssoData.lastName,
        lastSsoLoginAt: new Date(),
      });
      // Sync group memberships if groups claim is present
      if (ssoData.groups?.length) {
        await this.syncGroupMemberships(user.id, ssoData.groups, ssoData.workspaceId);
      }
      return user;
    }

    // New user — check seat limit before provisioning
    const seatCount = await this.userRepo.countByCompany(ssoData.companyId);
    const company = await this.companyRepo.findById(ssoData.companyId);
    if (seatCount >= company.seatsLimit) {
      throw new ForbiddenException('Seat limit reached — cannot provision new SSO user');
    }

    // Create user with default role
    user = await this.userRepo.create({
      email: ssoData.email,
      firstName: ssoData.firstName,
      lastName: ssoData.lastName,
      companyId: ssoData.companyId,
      workspaceId: ssoData.workspaceId,
      role: 'user', // default — workspace admin can promote
      authMethod: 'sso',
      passwordHash: null, // SSO users have no password
    });

    await this.auditService.logSync({
      workspaceId: ssoData.workspaceId,
      actorId: user.id,
      actorType: 'system',
      action: 'user.jit_provisioned',
      metadata: { email: ssoData.email, source: 'sso' },
    });

    return user;
  }
}
```

---

## RBAC/ABAC with CASL

### Role Hierarchy

```
company_owner
  |-- can do everything company_admin can, plus:
  |   - Delete workspaces
  |   - Modify company_admin users
  |   - Transfer company ownership
  |   - Delete company (triggers soft delete cascade)
  |
  +-- company_admin
        |-- can do everything workspace_admin can, plus:
        |   - Read all workspaces in company (cross-workspace aggregation)
        |   - Create/delete workspaces
        |   - Manage SSO connections
        |   - Manage company billing settings
        |   - Cannot modify company_owner users
        |
        +-- workspace_admin
              |-- can do everything user can, plus:
              |   - Manage users in their workspace (invite, remove, change role up to workspace_admin)
              |   - Manage workspace settings (custom fields, integrations, domains)
              |   - Export data (with audit trail)
              |   - View audit logs for their workspace
              |   - Cannot see other workspaces
              |
              +-- user
                    |-- Read recipients, campaigns, training (own workspace only)
                    |-- Create/update recipients (own workspace only)
                    |-- Read campaigns (own workspace only)
                    |-- Cannot delete, export, or manage settings
```

### Permission Inheritance Table

| Action | company_owner | company_admin | workspace_admin | user |
|--------|:---:|:---:|:---:|:---:|
| Read own workspace data | Y | Y | Y | Y |
| Create/update recipients | Y | Y | Y | Y |
| Delete recipients | Y | Y | Y | N |
| Export data | Y | Y | Y | N |
| Manage workspace settings | Y | Y | Y | N |
| Manage workspace users | Y | Y | Y | N |
| Read other workspace data | Y | Y (read-only) | N | N |
| Create/delete workspaces | Y | Y | N | N |
| Manage SSO connections | Y | Y | N | N |
| Manage billing | Y | Y | N | N |
| Modify company_admin users | Y | N | N | N |
| Delete workspaces | Y | N | N | N |
| Transfer ownership | Y | N | N | N |

### CASL Ability Factory (Complete)

```typescript
import { AbilityBuilder, PureAbility, AbilityClass } from '@casl/ability';

// Subject types matching your domain entities
type Actions = 'create' | 'read' | 'update' | 'delete' | 'manage' | 'export' | 'impersonate';
type Subjects =
  | 'Recipient'
  | 'Campaign'
  | 'Training'
  | 'Settings'
  | 'User'
  | 'Workspace'
  | 'Company'
  | 'SsoConnection'
  | 'AuditLog'
  | 'Domain'
  | 'ApiKey'
  | 'all';

type AppAbility = PureAbility<[Actions, Subjects]>;
const AppAbility = PureAbility as AbilityClass<AppAbility>;

@Injectable()
export class CaslAbilityFactory {
  createForUser(user: AuthenticatedUser, tenantContext: DomainContext): AppAbility {
    const { can, cannot, build } = new AbilityBuilder<AppAbility>(AppAbility);

    // --- COMPANY OWNER ---
    if (user.role === 'company_owner') {
      can('manage', 'all'); // unrestricted within company scope
    }

    // --- COMPANY ADMIN ---
    if (user.role === 'company_admin') {
      can('manage', 'all');
      // Cannot modify or delete the company owner
      cannot('update', 'User', { role: 'company_owner' });
      cannot('delete', 'User', { role: 'company_owner' });
      // Cannot delete workspaces (owner-only privilege)
      cannot('delete', 'Workspace');
      // Cannot transfer company ownership
      cannot('update', 'Company', ['ownerId']);
    }

    // --- WORKSPACE ADMIN ---
    if (user.role === 'workspace_admin') {
      // Full CRUD on workspace-scoped data
      can('manage', 'Recipient', { workspaceId: tenantContext.workspaceId });
      can('manage', 'Campaign', { workspaceId: tenantContext.workspaceId });
      can('manage', 'Training', { workspaceId: tenantContext.workspaceId });
      can('manage', 'Domain', { workspaceId: tenantContext.workspaceId });
      can('manage', 'Settings', { workspaceId: tenantContext.workspaceId });
      can('export', 'Recipient', { workspaceId: tenantContext.workspaceId });
      can('export', 'Campaign', { workspaceId: tenantContext.workspaceId });

      // User management within workspace
      can('read', 'User', { workspaceId: tenantContext.workspaceId });
      can('create', 'User', { workspaceId: tenantContext.workspaceId });
      can('update', 'User', { workspaceId: tenantContext.workspaceId });
      can('delete', 'User', { workspaceId: tenantContext.workspaceId });
      // Cannot modify users with higher roles
      cannot('update', 'User', { role: { $in: ['company_owner', 'company_admin'] } });
      cannot('delete', 'User', { role: { $in: ['company_owner', 'company_admin'] } });

      // Read-only audit logs for own workspace
      can('read', 'AuditLog', { workspaceId: tenantContext.workspaceId });

      // API key management for own workspace
      can('manage', 'ApiKey', { workspaceId: tenantContext.workspaceId });

      // Cannot access other workspaces, company-level settings, or SSO
      cannot('read', 'Workspace', { id: { $ne: tenantContext.workspaceId } });
      cannot('manage', 'SsoConnection');
      cannot('manage', 'Company');
    }

    // --- USER ---
    if (user.role === 'user') {
      can('read', 'Recipient', { workspaceId: tenantContext.workspaceId });
      can('create', 'Recipient', { workspaceId: tenantContext.workspaceId });
      can('update', 'Recipient', { workspaceId: tenantContext.workspaceId });
      can('read', 'Campaign', { workspaceId: tenantContext.workspaceId });
      can('read', 'Training', { workspaceId: tenantContext.workspaceId });

      // Cannot delete, export, manage settings, manage users
      cannot('delete', 'all');
      cannot('export', 'all');
      cannot('manage', 'Settings');
      cannot('manage', 'User');
      cannot('manage', 'ApiKey');
    }

    // --- SUBSCRIPTION ENFORCEMENT (applies to ALL roles) ---
    if (tenantContext.subscriptionStatus !== 'active' &&
        tenantContext.subscriptionStatus !== 'trialing') {
      cannot('create', 'all');
      cannot('update', 'all');
      cannot('delete', 'all');
      // Read-only mode when subscription is expired/cancelled
    }

    // --- IMPERSONATION RESTRICTIONS ---
    if (user.isImpersonated) {
      cannot('manage', 'Company');      // No company-level changes
      cannot('manage', 'SsoConnection');
      cannot('delete', 'Workspace');
      cannot('update', 'User', ['password', 'email', 'mfaSecret']); // No credential changes
      cannot('impersonate', 'all');     // Cannot chain impersonation
    }

    return build();
  }
}
```

### Field-Level Permissions

```typescript
// CASL supports field-level restrictions
// Example: user can read salary but not update it

// In ability factory:
can('read', 'User', ['firstName', 'lastName', 'email', 'role', 'salary'],
  { workspaceId: tenantContext.workspaceId });
can('update', 'User', ['firstName', 'lastName'],  // cannot update salary, email, role
  { workspaceId: tenantContext.workspaceId });

// In service — check field-level access:
async updateUser(userId: string, dto: UpdateUserDto, ability: AppAbility): Promise<User> {
  const user = await this.userRepo.findById(userId);
  if (!user) throw new NotFoundException();

  // Check each field being updated
  const fieldsToUpdate = Object.keys(dto);
  for (const field of fieldsToUpdate) {
    if (!ability.can('update', 'User', field)) {
      throw new ForbiddenException(`Cannot update field: ${field}`);
    }
  }

  return this.userRepo.update(userId, dto);
}
```

### Dynamic Permissions (MSSP/UC3 Custom Roles)

For MSSP (Managed Security Service Provider) tenants on Enterprise plan, workspace admins can create custom roles with fine-grained permissions.

```typescript
// Custom role definition stored in DB
interface CustomRoleDefinition {
  id: string;
  workspaceId: string;
  name: string;            // e.g., "Phishing Analyst", "Report Viewer"
  permissions: {
    subject: Subjects;
    action: Actions;
    fields?: string[];     // field-level restriction
    conditions?: Record<string, unknown>; // CASL conditions
  }[];
}

// In CaslAbilityFactory — extend for custom roles:
if (user.customRoleId) {
  const customRole = await this.redis.get(`custom-role:${user.customRoleId}`);
  if (customRole) {
    const role: CustomRoleDefinition = JSON.parse(customRole);
    for (const perm of role.permissions) {
      can(perm.action, perm.subject, perm.fields ?? undefined, perm.conditions ?? undefined);
    }
  }
}
```

### CheckAbility Decorator + PoliciesGuard

```typescript
// Decorator — declares required ability on controller method
export const CHECK_ABILITY_KEY = 'check_ability';

interface AbilityRequirement {
  action: Actions;
  subject: Subjects;
  field?: string;
}

export const CheckAbility = (...requirements: AbilityRequirement[]) =>
  SetMetadata(CHECK_ABILITY_KEY, requirements);

// Guard — enforces ability requirements
@Injectable()
export class PoliciesGuard implements CanActivate {
  constructor(
    private readonly reflector: Reflector,
    private readonly caslAbilityFactory: CaslAbilityFactory,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const requirements = this.reflector.get<AbilityRequirement[]>(
      CHECK_ABILITY_KEY,
      context.getHandler(),
    );
    if (!requirements || requirements.length === 0) return true;

    const req = context.switchToHttp().getRequest();
    const user: AuthenticatedUser = req.user;
    const tenantContext: DomainContext = req.tenantContext;

    const ability = this.caslAbilityFactory.createForUser(user, tenantContext);

    for (const requirement of requirements) {
      if (!ability.can(requirement.action, requirement.subject)) {
        throw new ForbiddenException(
          `Insufficient permissions: cannot ${requirement.action} ${requirement.subject}`,
        );
      }
    }

    return true;
  }
}

// Usage on controller:
@Controller('domains/:domainId/recipients')
@UseGuards(JwtAuthGuard, DomainContextGuard, PoliciesGuard)
export class RecipientsController {
  @Get()
  @CheckAbility({ action: 'read', subject: 'Recipient' })
  findAll(@TenantCtx() ctx: DomainContext) {
    return this.recipientService.findAll(ctx);
  }

  @Post()
  @CheckAbility({ action: 'create', subject: 'Recipient' })
  create(@Body() dto: CreateRecipientDto, @TenantCtx() ctx: DomainContext) {
    return this.recipientService.create(dto, ctx);
  }

  @Delete(':id')
  @CheckAbility({ action: 'delete', subject: 'Recipient' })
  delete(@Param('id') id: string, @TenantCtx() ctx: DomainContext) {
    return this.recipientService.delete(id, ctx);
  }

  @Post('export')
  @CheckAbility({ action: 'export', subject: 'Recipient' })
  export(@Body() dto: ExportDto, @TenantCtx() ctx: DomainContext) {
    return this.recipientService.export(dto, ctx);
  }
}
```

### Service-Layer Permission Check (Defense-in-Depth)

Guards are the first line. The service layer is the second — never rely on guards alone.

```typescript
@Injectable()
export class RecipientService {
  constructor(private readonly caslAbilityFactory: CaslAbilityFactory) {}

  async delete(id: string, ctx: DomainContext, user: AuthenticatedUser): Promise<void> {
    const ability = this.caslAbilityFactory.createForUser(user, ctx);
    const recipient = await this.recipientRepo.findById(id, ctx.domainId);
    if (!recipient) throw new NotFoundException();

    // Service-layer check — even if guard was bypassed or misconfigured
    if (!ability.can('delete', 'Recipient')) {
      throw new ForbiddenException('Cannot delete recipients');
    }

    await this.recipientRepo.softDelete(id, ctx.domainId);
  }
}
```

---

## Admin Impersonation Security

### Impersonation Flow

```
1. Admin navigates to admin panel → user detail page
2. Admin clicks "Impersonate" → modal requires:
   - Reason (free text, 10+ chars, REQUIRED, permanently stored)
   - Confirmation checkbox ("I understand this will be audited")
3. POST /admin/workspaces/:workspaceId/impersonate
   → Validates admin has impersonation rights (company_owner or company_admin)
   → Validates target workspace belongs to admin's company
   → Validates admin is not already impersonating (no chaining)
   → Validates impersonation rate limit (max 5 per admin per hour)
   → Creates time-limited impersonation token (max 1 hour)
   → Logs: admin.impersonation_started (synchronous, not async)
   → Notifies workspace admin via email: "Admin X is impersonating in your workspace"
4. Admin's browser receives impersonation token
   → Original admin session is preserved (stored separately)
   → Impersonation token set as active session
   → UI shows prominent "Impersonating" banner with countdown
5. Every action during impersonation:
   → actorType = 'admin_impersonation'
   → impersonatorId = admin's original ID
   → All audit logs tagged with impersonation session ID
6. Auto-expiry at 1 hour OR admin clicks "End Impersonation"
   → DELETE /admin/impersonation/:token
   → Original admin session restored
   → Logs: admin.impersonation_ended (with duration and action count)
7. 30-minute alert: if impersonation > 30 minutes, admin's manager notified
```

### Impersonation Token Structure

```typescript
interface ImpersonationTokenPayload extends AccessTokenPayload {
  isImpersonated: true;              // always true
  impersonatorId: string;            // original admin user ID
  impersonationSessionId: string;    // links to impersonation_sessions table
  impersonationExpiresAt: number;    // Unix seconds — hard max 1 hour from creation
  impersonationReason: string;       // stored in token for audit correlation

  // Restrictions embedded in token (enforced by guards)
  aud: 'api';                        // NOT 'admin' — cannot access admin panel
}
```

### ImpersonationService

```typescript
@Injectable()
export class ImpersonationService {
  private readonly MAX_DURATION_HOURS = 1;
  private readonly RATE_LIMIT_MAX = 5;
  private readonly RATE_LIMIT_WINDOW = 3600; // 1 hour
  private readonly MANAGER_ALERT_MINUTES = 30;

  async createSession(
    adminId: string,
    workspaceId: string,
    dto: ImpersonateDto,
  ): Promise<ImpersonationResult> {
    // 1. Verify admin has impersonation rights
    const admin = await this.userRepo.findById(adminId);
    if (!['company_owner', 'company_admin'].includes(admin.role)) {
      throw new ForbiddenException('Only company owners/admins can impersonate');
    }

    // 2. Verify target workspace belongs to admin's company
    const workspace = await this.workspaceRepo.findById(workspaceId);
    if (workspace.companyId !== admin.companyId) {
      throw new ForbiddenException('Cannot impersonate in another company');
    }

    // 3. Verify admin is not already impersonating
    const activeSession = await this.db.query.impersonationSessions.findFirst({
      where: and(
        eq(impersonationSessions.adminId, adminId),
        gt(impersonationSessions.expiresAt, new Date()),
        isNull(impersonationSessions.endedAt),
      ),
    });
    if (activeSession) {
      throw new ConflictException('Already impersonating — end current session first');
    }

    // 4. Rate limit check
    const rateKey = `impersonation-rate:${adminId}`;
    const count = await this.redis.incr(rateKey);
    if (count === 1) await this.redis.expire(rateKey, this.RATE_LIMIT_WINDOW);
    if (count > this.RATE_LIMIT_MAX) {
      throw new TooManyRequestsException(
        `Impersonation rate limit: max ${this.RATE_LIMIT_MAX} per hour`,
      );
    }

    // 5. Create session
    const sessionToken = randomBytes(32).toString('hex');
    const expiresAt = addHours(new Date(), this.MAX_DURATION_HOURS);

    const [session] = await this.db.insert(impersonationSessions).values({
      adminId,
      workspaceId,
      impersonatedUserId: dto.userId ?? null,
      reason: dto.reason,
      sessionToken,
      expiresAt,
    }).returning();

    // 6. Synchronous audit log (must not be dropped)
    await this.auditService.logSync({
      companyId: admin.companyId,
      workspaceId,
      actorId: adminId,
      actorType: 'admin',
      action: 'admin.impersonation_started',
      metadata: {
        reason: dto.reason,
        targetUserId: dto.userId,
        expiresAt: expiresAt.toISOString(),
        sessionId: session.id,
      },
    });

    // 7. Notify workspace admin
    await this.notificationService.notifyWorkspaceAdmins(workspaceId, {
      type: 'impersonation_started',
      adminEmail: admin.email,
      reason: dto.reason,
      expiresAt,
    });

    // 8. Schedule 30-minute manager alert
    await this.alertQueue.add('impersonation-alert', {
      adminId,
      sessionId: session.id,
      workspaceId,
    }, {
      delay: this.MANAGER_ALERT_MINUTES * 60 * 1000,
      jobId: `imp-alert:${session.id}`,
    });

    // 9. Generate impersonation access token
    const targetUser = dto.userId
      ? await this.userRepo.findById(dto.userId)
      : await this.userRepo.findWorkspaceDefaultUser(workspaceId);

    const impersonationToken = this.jwtService.sign({
      sub: targetUser.id,
      email: targetUser.email,
      companyId: admin.companyId,
      workspaceId,
      role: targetUser.role,
      mfa: true,
      sso: false,
      isImpersonated: true,
      impersonatorId: adminId,
      impersonationSessionId: session.id,
      impersonationExpiresAt: Math.floor(expiresAt.getTime() / 1000),
      impersonationReason: dto.reason,
      tier: workspace.company.subscriptionTier,
      aud: 'api', // NOT 'admin'
    }, { expiresIn: '1h', algorithm: 'RS256' });

    return { impersonationToken, expiresAt, sessionId: session.id };
  }

  async endSession(token: string, adminId: string): Promise<void> {
    const session = await this.db.query.impersonationSessions.findFirst({
      where: and(
        eq(impersonationSessions.sessionToken, token),
        eq(impersonationSessions.adminId, adminId),
      ),
    });
    if (!session) throw new NotFoundException('Impersonation session not found');

    await this.db.update(impersonationSessions)
      .set({ endedAt: new Date() })
      .where(eq(impersonationSessions.id, session.id));

    // Cancel the 30-minute alert if it hasn't fired
    await this.alertQueue.remove(`imp-alert:${session.id}`);

    // Revoke the impersonation access token
    // (token JTI is stored in session metadata for revocation)
    await this.tokenService.revokeAccessToken(session.tokenJti, session.expiresAt);

    await this.auditService.logSync({
      companyId: session.companyId,
      workspaceId: session.workspaceId,
      actorId: adminId,
      actorType: 'admin',
      action: 'admin.impersonation_ended',
      metadata: {
        sessionId: session.id,
        durationMinutes: Math.round(
          (Date.now() - session.createdAt.getTime()) / 60000,
        ),
      },
    });
  }
}
```

### ImpersonationGuard

```typescript
@Injectable()
export class ImpersonationGuard implements CanActivate {
  async canActivate(context: ExecutionContext): Promise<boolean> {
    const req = context.switchToHttp().getRequest();
    const user = req.user as AccessTokenPayload;

    if (!user?.isImpersonated) return true; // Not impersonating — pass through

    // Block access to admin panel routes
    const path = req.path;
    if (path.startsWith('/admin')) {
      throw new ForbiddenException('Admin panel access denied during impersonation');
    }

    // Block impersonation of another user (no chaining)
    if (path.includes('/impersonate')) {
      throw new ForbiddenException('Cannot impersonate while impersonating');
    }

    // Verify impersonation token hasn't expired (belt + suspenders with JWT exp)
    if (user.impersonationExpiresAt < Math.floor(Date.now() / 1000)) {
      throw new UnauthorizedException('Impersonation session expired');
    }

    // Verify session is still active in DB (admin may have ended it)
    const session = await this.impersonationService.validateSession(
      user.impersonationSessionId,
    );
    if (!session) {
      throw new UnauthorizedException('Impersonation session ended');
    }

    // Tag request for audit interceptor
    req.impersonationContext = {
      impersonatorId: user.impersonatorId,
      sessionId: user.impersonationSessionId,
      reason: user.impersonationReason,
    };

    return true;
  }
}
```

### Audit Interceptor (Tags Every Action During Impersonation)

```typescript
@Injectable()
export class AuditInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const req = context.switchToHttp().getRequest();
    const start = Date.now();

    return next.handle().pipe(
      tap(async () => {
        // Only audit mutations (POST, PATCH, PUT, DELETE)
        if (['GET', 'HEAD', 'OPTIONS'].includes(req.method)) return;

        const auditEntry: Partial<AuditLog> = {
          actorId: req.user?.sub,
          action: `${req.method} ${req.route?.path}`,
          resourceType: this.extractResourceType(req.route?.path),
          resourceId: req.params?.id,
          ipAddress: req.ip,
          userAgent: req.headers['user-agent'],
          status: 'success',
        };

        // Impersonation tagging — attaches to every audit entry
        if (req.impersonationContext) {
          auditEntry.actorType = 'admin_impersonation';
          auditEntry.metadata = {
            ...auditEntry.metadata,
            impersonatorId: req.impersonationContext.impersonatorId,
            impersonationSessionId: req.impersonationContext.sessionId,
            impersonationReason: req.impersonationContext.reason,
            durationMs: Date.now() - start,
          };
        } else {
          auditEntry.actorType = req.user?.isImpersonated ? 'admin_impersonation' : 'user';
        }

        await this.auditService.log(auditEntry);
      }),
    );
  }

  private extractResourceType(path?: string): string {
    if (!path) return 'unknown';
    const segments = path.split('/').filter(Boolean);
    // Find the first non-param segment (doesn't start with ':')
    return segments.find(s => !s.startsWith(':')) ?? 'unknown';
  }
}
```

---

## Account Security

### Password Policy

| Requirement | Value | Rationale |
|-------------|-------|-----------|
| Minimum length | 12 characters | NIST SP 800-63B recommendation |
| Maximum length | 128 characters | Prevent bcrypt DoS (72 byte limit) |
| Complexity | At least 1 uppercase, 1 lowercase, 1 digit, 1 special | Defense against dictionary attacks |
| Breach check | k-anonymity via Have I Been Pwned API | Reject known compromised passwords |
| History | Cannot reuse last 5 passwords | Prevent password rotation gaming |
| Expiry | None (NIST recommends against mandatory rotation) | Mandatory rotation leads to weaker passwords |

```typescript
@Injectable()
export class PasswordPolicyService {
  async validatePassword(password: string, userId?: string): Promise<ValidationResult> {
    const errors: string[] = [];

    // Length
    if (password.length < 12) errors.push('Password must be at least 12 characters');
    if (password.length > 128) errors.push('Password must be at most 128 characters');

    // Complexity
    if (!/[A-Z]/.test(password)) errors.push('Must contain at least one uppercase letter');
    if (!/[a-z]/.test(password)) errors.push('Must contain at least one lowercase letter');
    if (!/[0-9]/.test(password)) errors.push('Must contain at least one digit');
    if (!/[^A-Za-z0-9]/.test(password)) errors.push('Must contain at least one special character');

    // Breach check via k-anonymity (HIBP API)
    const sha1 = createHash('sha1').update(password).digest('hex').toUpperCase();
    const prefix = sha1.substring(0, 5);
    const suffix = sha1.substring(5);
    const response = await this.httpService.axiosRef.get(
      `https://api.pwnedpasswords.com/range/${prefix}`,
    );
    const breached = response.data.split('\n').some(
      (line: string) => line.startsWith(suffix),
    );
    if (breached) errors.push('This password has appeared in a data breach — choose another');

    // History check (if updating existing password)
    if (userId) {
      const previousHashes = await this.db.query.passwordHistory.findMany({
        where: eq(passwordHistory.userId, userId),
        orderBy: [desc(passwordHistory.createdAt)],
        limit: 5,
      });
      for (const prev of previousHashes) {
        if (await bcrypt.compare(password, prev.passwordHash)) {
          errors.push('Cannot reuse any of your last 5 passwords');
          break;
        }
      }
    }

    return { valid: errors.length === 0, errors };
  }
}
```

### Brute Force Protection

| Threshold | Action |
|-----------|--------|
| 3 failed attempts | CAPTCHA challenge presented on next attempt |
| 5 failed attempts | Account locked for 15 minutes |
| 10 failed attempts | Account locked for 1 hour, email notification sent to user |
| 20 failed attempts | Account locked for 24 hours, security team alerted |
| 5 failed attempts from same IP (any account) | IP rate limited for 15 minutes |

```typescript
@Injectable()
export class LockoutService {
  private readonly THRESHOLDS = [
    { attempts: 3, action: 'captcha' as const },
    { attempts: 5, action: 'lock' as const, durationMinutes: 15 },
    { attempts: 10, action: 'lock' as const, durationMinutes: 60, notify: true },
    { attempts: 20, action: 'lock' as const, durationMinutes: 1440, alert: true },
  ];

  async recordFailedAttempt(email: string, ip: string): Promise<LockoutStatus> {
    const accountKey = `lockout:account:${email}`;
    const ipKey = `lockout:ip:${ip}`;

    // Increment attempt counter (expires after 24 hours of no attempts)
    const accountAttempts = await this.redis.incr(accountKey);
    if (accountAttempts === 1) await this.redis.expire(accountKey, 86400);

    const ipAttempts = await this.redis.incr(ipKey);
    if (ipAttempts === 1) await this.redis.expire(ipKey, 900); // 15-minute window

    // IP-level rate limit
    if (ipAttempts > 5) {
      await this.redis.setex(`lockout:ip-blocked:${ip}`, 900, '1');
      return { locked: true, reason: 'ip_rate_limit', retryAfterMinutes: 15 };
    }

    // Account-level lockout (iterate thresholds in reverse to find highest match)
    for (const threshold of [...this.THRESHOLDS].reverse()) {
      if (accountAttempts >= threshold.attempts) {
        if (threshold.action === 'captcha') {
          return { locked: false, requiresCaptcha: true, attempts: accountAttempts };
        }

        const lockKey = `lockout:locked:${email}`;
        await this.redis.setex(lockKey, threshold.durationMinutes * 60, '1');

        if (threshold.notify) {
          await this.emailService.sendSecurityAlert(email, {
            type: 'account_lockout',
            attempts: accountAttempts,
            ip,
            durationMinutes: threshold.durationMinutes,
          });
        }
        if (threshold.alert) {
          await this.securityAlertService.alert({
            type: 'excessive_login_failures',
            email, ip,
            attempts: accountAttempts,
          });
        }

        return {
          locked: true,
          reason: 'too_many_attempts',
          retryAfterMinutes: threshold.durationMinutes,
          attempts: accountAttempts,
        };
      }
    }

    return { locked: false, attempts: accountAttempts };
  }

  async isLocked(email: string, ip: string): Promise<boolean> {
    const [accountLocked, ipBlocked] = await Promise.all([
      this.redis.exists(`lockout:locked:${email}`),
      this.redis.exists(`lockout:ip-blocked:${ip}`),
    ]);
    return accountLocked === 1 || ipBlocked === 1;
  }

  async resetOnSuccess(email: string): Promise<void> {
    await this.redis.del(`lockout:account:${email}`);
    // Do NOT reset lockout:locked — it must expire naturally
  }
}
```

### Password Reset Flow

```
1. User requests reset: POST /auth/forgot-password { email }
   - Always return 200 (don't reveal if email exists)
   - Generate cryptographically random token (64 bytes, base64url)
   - Hash token (SHA-256) and store in DB with: userId, tokenHash, expiresAt (1 hour), usedAt (null)
   - Send email with reset link containing the raw token
   - Rate limit: max 3 reset emails per email per hour

2. User clicks link: GET /auth/reset-password?token=xxx
   - Frontend renders password form (token stays in URL, NOT in query string if possible — use fragment)

3. User submits new password: POST /auth/reset-password { token, newPassword }
   - Hash token, look up in DB
   - Validate: exists, not expired (1 hour), not used (usedAt is null)
   - Validate new password against password policy
   - Hash new password (bcrypt cost 12)
   - Update user's password
   - Mark token as used (usedAt = now)
   - Invalidate ALL existing sessions for this user
   - Revoke ALL refresh tokens for this user
   - Add old password hash to password history
   - Send confirmation email: "Your password was changed"
   - Log: user.password_reset (with IP, userAgent)
```

```typescript
@Injectable()
export class PasswordResetService {
  async requestReset(email: string, ip: string): Promise<void> {
    // Rate limit
    const rateKey = `password-reset-rate:${email}`;
    const count = await this.redis.incr(rateKey);
    if (count === 1) await this.redis.expire(rateKey, 3600);
    if (count > 3) return; // Silent — don't reveal rate limiting

    const user = await this.userRepo.findByEmail(email);
    if (!user) return; // Silent — don't reveal email existence

    // Invalidate any existing reset tokens for this user
    await this.db.update(passwordResetTokens)
      .set({ usedAt: new Date() })
      .where(and(
        eq(passwordResetTokens.userId, user.id),
        isNull(passwordResetTokens.usedAt),
      ));

    const rawToken = randomBytes(64).toString('base64url');
    const tokenHash = createHash('sha256').update(rawToken).digest('hex');

    await this.db.insert(passwordResetTokens).values({
      userId: user.id,
      tokenHash,
      expiresAt: addHours(new Date(), 1),
    });

    await this.emailService.sendPasswordReset(email, rawToken);
  }

  async resetPassword(rawToken: string, newPassword: string, ip: string): Promise<void> {
    const tokenHash = createHash('sha256').update(rawToken).digest('hex');

    const storedToken = await this.db.query.passwordResetTokens.findFirst({
      where: and(
        eq(passwordResetTokens.tokenHash, tokenHash),
        gt(passwordResetTokens.expiresAt, new Date()),
        isNull(passwordResetTokens.usedAt),
      ),
    });
    if (!storedToken) throw new UnauthorizedException('Invalid or expired reset token');

    // Validate new password
    const validation = await this.passwordPolicy.validatePassword(newPassword, storedToken.userId);
    if (!validation.valid) throw new BadRequestException(validation.errors);

    // Hash and update
    const passwordHash = await bcrypt.hash(newPassword, 12);
    const user = await this.userRepo.findById(storedToken.userId);

    // Save old hash to history
    await this.db.insert(passwordHistory).values({
      userId: user.id,
      passwordHash: user.passwordHash,
    });

    // Update password
    await this.userRepo.update(user.id, { passwordHash });

    // Mark token as used
    await this.db.update(passwordResetTokens)
      .set({ usedAt: new Date() })
      .where(eq(passwordResetTokens.id, storedToken.id));

    // Invalidate all sessions and tokens
    await this.sessionService.invalidateAllSessions(user.id);
    await this.tokenService.revokeAllUserTokens(user.id);

    // Notify user
    await this.emailService.sendPasswordChanged(user.email);

    // Audit
    await this.auditService.logSync({
      actorId: user.id,
      actorType: 'user',
      action: 'user.password_reset',
      metadata: { ip, method: 'reset_link' },
    });
  }
}
```

### Email Change Flow

```
1. User requests email change: POST /auth/change-email { newEmail, password }
   - Verify current password
   - Validate new email format and uniqueness within workspace
   - Send verification to OLD email: "Someone requested to change your email. If this wasn't you, click here."
   - Send verification to NEW email: "Click to verify this email address"
   - Both links contain different single-use tokens
   - Both tokens must be clicked within 24 hours

2. User clicks OLD email confirmation: verifies intent
3. User clicks NEW email confirmation: verifies ownership
4. Only after BOTH confirmations: email is updated
   - All sessions invalidated (email is in token claims)
   - Audit: user.email_changed (old and new, actor)
```

### Account Deletion

| Phase | Timing | What Happens |
|-------|--------|-------------|
| Soft delete request | Day 0 | User requests deletion. Account marked `deletedAt = now`. Login disabled. Email sent: "Your account will be permanently deleted in 30 days." |
| Grace period | Days 0-30 | Account is recoverable. User can contact support to cancel. Data still exists. |
| PII scrub | Day 30 | Email, name, phone replaced with `[deleted-{hash}]`. Password hash removed. Profile photo deleted. |
| Hard delete | Day 30 | Audit logs retained (with scrubbed actor). Recipient data retained (owned by workspace, not user). Session data already expired. |

---

## API Key Authentication

### Key Generation

```typescript
@Injectable()
export class ApiKeyService {
  // Prefix format: sk_live_ (production) or sk_test_ (sandbox)
  // This allows quick identification of key type in logs without revealing the key
  private readonly KEY_PREFIX = 'sk_live_';
  private readonly KEY_BYTES = 32;

  async createKey(
    userId: string,
    workspaceId: string,
    dto: CreateApiKeyDto,
  ): Promise<{ key: string; keyId: string }> {
    // Generate cryptographically random key
    const rawKey = this.KEY_PREFIX + randomBytes(this.KEY_BYTES).toString('base64url');

    // Hash for storage — raw key is NEVER stored
    const keyHash = createHash('sha256').update(rawKey).digest('hex');

    // Store only the hash + metadata
    const [record] = await this.db.insert(apiKeys).values({
      userId,
      workspaceId,
      companyId: dto.companyId,
      name: dto.name,
      keyHash,
      keyPrefix: rawKey.substring(0, 12), // "sk_live_XXXX" — for display in UI
      permissions: dto.permissions,        // scoped permission set
      expiresAt: dto.expiresAt ?? null,    // optional expiry
      rateLimitPerMinute: dto.rateLimitPerMinute ?? 60,
    }).returning();

    await this.auditService.logSync({
      workspaceId,
      actorId: userId,
      actorType: 'user',
      action: 'api_key.created',
      metadata: { keyPrefix: rawKey.substring(0, 12), name: dto.name },
    });

    // Return raw key ONCE — it will never be shown again
    return { key: rawKey, keyId: record.id };
  }
}
```

### Key Storage Schema

```typescript
export const apiKeys = pgTable('api_keys', {
  id: uuid('id').defaultRandom().primaryKey(),
  userId: uuid('user_id').notNull(),          // who created it
  companyId: uuid('company_id').notNull(),
  workspaceId: uuid('workspace_id').notNull(),
  name: text('name').notNull(),               // human-readable label
  keyHash: text('key_hash').notNull(),         // SHA-256 of raw key
  keyPrefix: text('key_prefix').notNull(),     // first 12 chars for UI display
  permissions: jsonb('permissions').$type<ApiKeyPermission[]>().notNull(),
  rateLimitPerMinute: integer('rate_limit_per_minute').notNull().default(60),
  lastUsedAt: timestamp('last_used_at'),
  expiresAt: timestamp('expires_at'),
  revokedAt: timestamp('revoked_at'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
}, (table) => ({
  keyHashIdx: uniqueIndex('idx_api_key_hash').on(table.keyHash),
  workspaceIdx: index('idx_api_key_workspace').on(table.workspaceId),
}));

interface ApiKeyPermission {
  subject: string;     // 'Recipient', 'Campaign', etc.
  actions: string[];   // ['read'], ['read', 'create'], etc.
}
```

### API Key Guard

```typescript
@Injectable()
export class ApiKeyGuard implements CanActivate {
  constructor(
    @Inject(DB_TOKEN) private readonly db: DB,
    @Inject('REDIS') private readonly redis: Redis,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const req = context.switchToHttp().getRequest();
    const authHeader = req.headers['authorization'];

    // API key auth uses Bearer scheme with sk_ prefix
    if (!authHeader?.startsWith('Bearer sk_')) return false;

    const rawKey = authHeader.substring(7); // strip "Bearer "
    const keyHash = createHash('sha256').update(rawKey).digest('hex');

    // Check cache first (valid keys cached for 5 minutes)
    const cached = await this.redis.get(`apikey:${keyHash}`);
    let keyRecord: ApiKeyRecord;

    if (cached) {
      keyRecord = JSON.parse(cached);
    } else {
      const record = await this.db.query.apiKeys.findFirst({
        where: and(
          eq(apiKeys.keyHash, keyHash),
          isNull(apiKeys.revokedAt),
        ),
      });
      if (!record) throw new UnauthorizedException('Invalid API key');

      // Check expiry
      if (record.expiresAt && record.expiresAt < new Date()) {
        throw new UnauthorizedException('API key expired');
      }

      keyRecord = record;
      await this.redis.setex(`apikey:${keyHash}`, 300, JSON.stringify(record));
    }

    // Rate limiting (separate from user session rate limits)
    const rateKey = `apikey-rate:${keyRecord.id}`;
    const requests = await this.redis.incr(rateKey);
    if (requests === 1) await this.redis.expire(rateKey, 60);
    if (requests > keyRecord.rateLimitPerMinute) {
      throw new TooManyRequestsException('API key rate limit exceeded');
    }

    // Update last used (debounced — only if >5 min since last update)
    const lastUpdateKey = `apikey-lastused:${keyRecord.id}`;
    const shouldUpdate = await this.redis.set(lastUpdateKey, '1', 'EX', 300, 'NX');
    if (shouldUpdate) {
      // Fire-and-forget DB update
      this.db.update(apiKeys)
        .set({ lastUsedAt: new Date() })
        .where(eq(apiKeys.id, keyRecord.id))
        .execute()
        .catch(() => {}); // non-critical
    }

    // Attach API key context to request (similar shape to JWT user)
    req.user = {
      sub: keyRecord.userId,
      companyId: keyRecord.companyId,
      workspaceId: keyRecord.workspaceId,
      role: 'api_key',
      permissions: keyRecord.permissions,
      isImpersonated: false,
      mfa: false,
      sso: false,
    };
    req.isApiKey = true;

    return true;
  }
}
```

### Key Rotation (Overlap Period)

```
1. User requests rotation: POST /api-keys/:id/rotate
2. New key generated, old key NOT immediately revoked
3. Both old and new keys work during overlap period (configurable, default 24 hours)
4. Old key auto-revoked after overlap period (BullMQ delayed job)
5. User updates their integration with new key during overlap
6. Audit: api_key.rotated (old key prefix, new key prefix, overlap duration)
```

```typescript
async rotateKey(keyId: string, userId: string): Promise<{ newKey: string; overlapEndsAt: Date }> {
  const oldKey = await this.db.query.apiKeys.findFirst({
    where: and(eq(apiKeys.id, keyId), eq(apiKeys.userId, userId)),
  });
  if (!oldKey) throw new NotFoundException();

  // Create new key with same permissions
  const { key: newKey } = await this.createKey(userId, oldKey.workspaceId, {
    name: `${oldKey.name} (rotated)`,
    companyId: oldKey.companyId,
    permissions: oldKey.permissions,
    rateLimitPerMinute: oldKey.rateLimitPerMinute,
  });

  // Schedule old key revocation after overlap period
  const overlapEndsAt = addHours(new Date(), 24);
  await this.revokeQueue.add('revoke-api-key', {
    keyId: oldKey.id,
  }, {
    delay: 24 * 60 * 60 * 1000,
    jobId: `revoke:${oldKey.id}`,
  });

  await this.auditService.logSync({
    workspaceId: oldKey.workspaceId,
    actorId: userId,
    actorType: 'user',
    action: 'api_key.rotated',
    metadata: {
      oldKeyPrefix: oldKey.keyPrefix,
      overlapHours: 24,
    },
  });

  return { newKey, overlapEndsAt };
}
```

---

## Multi-Tenant Auth Patterns

### Workspace Switching

When a user switches workspaces, they get a new token with different workspace claims. The refresh token is NOT reused — a new token pair is issued.

```typescript
@Post('auth/switch-workspace')
@UseGuards(JwtAuthGuard)
async switchWorkspace(
  @Body('workspaceId') targetWorkspaceId: string,
  @CurrentUser() user: AccessTokenPayload,
  @Res({ passthrough: true }) res: Response,
): Promise<{ accessToken: string }> {
  // Verify user belongs to target workspace
  const membership = await this.membershipRepo.findByUserAndWorkspace(
    user.sub, targetWorkspaceId,
  );
  if (!membership) throw new ForbiddenException('Not a member of this workspace');

  // Verify workspace is in same company
  const workspace = await this.workspaceRepo.findById(targetWorkspaceId);
  if (workspace.companyId !== user.companyId) {
    throw new ForbiddenException('Cannot switch to workspace in another company');
  }

  // Issue new token pair for target workspace
  const fullUser = await this.userRepo.findById(user.sub);
  const tokenPair = await this.tokenService.generateTokenPair(
    { ...fullUser, role: membership.role }, // role may differ per workspace
    targetWorkspaceId,
  );

  // Update session
  await this.sessionService.extendSession(user.sub, user.deviceFingerprint, {
    workspaceId: targetWorkspaceId,
    role: membership.role,
  });

  this.setTokenCookies(res, tokenPair);
  return { accessToken: tokenPair.accessToken };
}
```

### Cross-Workspace Operations for Company Admin

Company admins can read data across all workspaces in their company. Write operations are restricted to a single workspace at a time.

```typescript
// Cross-workspace read — aggregation endpoint
@Get('company/dashboard')
@UseGuards(JwtAuthGuard, CompanyAdminGuard)
@CheckAbility({ action: 'read', subject: 'Workspace' })
async companyDashboard(@CurrentUser() user: AccessTokenPayload): Promise<CompanyDashboard> {
  // Query scoped to companyId — NOT workspaceId
  const workspaces = await this.workspaceRepo.findByCompany(user.companyId);
  const stats = await Promise.all(
    workspaces.map(ws => this.statsService.getWorkspaceStats(ws.id)),
  );

  return {
    workspaces: stats,
    totalRecipients: stats.reduce((sum, s) => sum + s.recipientCount, 0),
    totalCampaigns: stats.reduce((sum, s) => sum + s.campaignCount, 0),
  };
}

// Cross-workspace write — REQUIRES explicit workspaceId
@Post('company/workspaces/:workspaceId/recipients')
@UseGuards(JwtAuthGuard, CompanyAdminGuard, DomainContextGuard)
@CheckAbility({ action: 'create', subject: 'Recipient' })
async createInWorkspace(
  @Param('workspaceId') workspaceId: string,
  @Body() dto: CreateRecipientDto,
  @CurrentUser() user: AccessTokenPayload,
): Promise<Recipient> {
  // DomainContextGuard validates workspaceId belongs to user's company
  // Write is scoped to the explicit workspaceId — no ambiguity
  return this.recipientService.create(dto, { ...user, workspaceId });
}
```

### Subscription-Gated Feature Access

```typescript
// Decorator for plan-gated features
export const RequirePlan = (...tiers: SubscriptionTier[]) =>
  SetMetadata('required_plan', tiers);

// Guard that checks subscription tier from JWT claims
@Injectable()
export class PlanGateGuard implements CanActivate {
  constructor(private readonly reflector: Reflector) {}

  canActivate(context: ExecutionContext): boolean {
    const requiredTiers = this.reflector.get<SubscriptionTier[]>(
      'required_plan',
      context.getHandler(),
    );
    if (!requiredTiers || requiredTiers.length === 0) return true;

    const req = context.switchToHttp().getRequest();
    const user = req.user as AccessTokenPayload;

    if (!requiredTiers.includes(user.tier)) {
      throw new ForbiddenException(
        `This feature requires a ${requiredTiers.join(' or ')} plan`,
      );
    }
    return true;
  }
}

// Usage:
@Post('sso/connections')
@RequirePlan('business', 'enterprise')
@CheckAbility({ action: 'manage', subject: 'SsoConnection' })
async createSsoConnection(@Body() dto: CreateSsoConnectionDto) {
  return this.ssoService.create(dto);
}

@Get('audit-logs')
@RequirePlan('pro', 'business', 'enterprise')
@CheckAbility({ action: 'read', subject: 'AuditLog' })
async getAuditLogs(@Query() filter: AuditFilterDto) {
  return this.auditRepo.findAll(filter);
}
```

### Tenant Suspension Handling

When a company's subscription is suspended (non-payment, ToS violation), all auth is blocked except access to the billing portal.

```typescript
@Injectable()
export class TenantSuspensionGuard implements CanActivate {
  async canActivate(context: ExecutionContext): Promise<boolean> {
    const req = context.switchToHttp().getRequest();
    const tenantContext = req.tenantContext as DomainContext;
    if (!tenantContext) return true; // Pre-auth routes

    if (tenantContext.subscriptionStatus === 'suspended') {
      const path = req.path;

      // Allow ONLY billing-related routes
      const allowedPaths = [
        '/billing',
        '/billing/portal',
        '/billing/invoices',
        '/auth/logout',
        '/auth/refresh',
      ];

      if (!allowedPaths.some(p => path.startsWith(p))) {
        throw new ForbiddenException({
          code: 'TENANT_SUSPENDED',
          message: 'Account suspended. Please update billing to restore access.',
          billingUrl: '/billing/portal',
        });
      }
    }

    return true;
  }
}
```

### SSO Per Workspace (Multi-IdP Routing)

Different workspaces in the same company can have different SSO providers. The login flow routes to the correct IdP based on workspace selection.

```typescript
// Login page: user selects workspace first (or enters email domain)
@Get('auth/sso/discover')
async discoverSso(@Query('email') email: string): Promise<SsoDiscoveryResult> {
  const emailDomain = email.split('@')[1];

  // Look up SSO connections by email domain mapping
  const connections = await this.db.query.ssoConnections.findMany({
    where: and(
      eq(ssoConnections.emailDomain, emailDomain),
      eq(ssoConnections.isActive, true),
    ),
    with: { workspace: { columns: { id: true, name: true } } },
  });

  if (connections.length === 0) {
    return { ssoAvailable: false };
  }

  if (connections.length === 1) {
    // Single workspace — redirect directly
    return {
      ssoAvailable: true,
      autoRedirect: true,
      authUrl: await this.oauthService.initiateOAuth(
        connections[0].workspaceId,
        connections[0].provider,
      ),
    };
  }

  // Multiple workspaces — user must choose
  return {
    ssoAvailable: true,
    autoRedirect: false,
    workspaces: connections.map(c => ({
      workspaceId: c.workspace.id,
      workspaceName: c.workspace.name,
      provider: c.provider,
    })),
  };
}
```

| Scenario | Routing Logic |
|----------|---------------|
| 1 workspace, 1 IdP | Auto-redirect to IdP |
| 1 workspace, multiple IdPs (e.g., SAML + Google) | Show IdP picker |
| Multiple workspaces, same IdP domain | Show workspace picker, then redirect |
| Multiple workspaces, different IdPs | Show workspace picker, each routes to its own IdP |
| No SSO configured | Fall back to password login |

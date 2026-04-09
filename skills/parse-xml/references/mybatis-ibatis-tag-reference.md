# MyBatis 3.x / iBatis 2.x XML Tag Complete Reference

> Comprehensive technical reference for parsing MyBatis and iBatis XML configuration and mapper files.  
> Date: 2026-04-09

---

## 1. Framework Identification

### 1.1 Root Element Detection

| Framework | Root Element | Namespace |
|-----------|--------------|-----------|
| MyBatis 3.x | `<mapper namespace="...">` | `http://mybatis.org/dtd/mybatis-3-mapper.dtd` |
| iBatis 2.x | `<sqlMap namespace="...">` | `http://ibatis.apache.org/dtd/sql-map-2.dtd` |

### 1.2 Configuration Files

| Framework | Config Root | DTD |
|-----------|-------------|-----|
| MyBatis 3.x | `<configuration>` | `mybatis-3-config.dtd` |
| iBatis 2.x | `<sqlMapConfig>` | `sql-map-config-2.dtd` |

---

## 2. MyBatis 3.x Configuration XML Tags

### 2.1 Configuration Structure

```xml
<configuration>
  <properties/>
  <settings/>
  <typeAliases/>
  <typeHandlers/>
  <objectFactory/>
  <objectWrapperFactory/>
  <reflectorFactory/>
  <plugins/>
  <environments/>
  <databaseIdProvider/>
  <mappers/>
</configuration>
```

### 2.2 Tag Reference

| Tag | Purpose | Key Attributes | Child Tags |
|-----|---------|----------------|------------|
| `<properties>` | External properties | resource, url | `<property>` |
| `<settings>` | Global settings | - | `<setting>` |
| `<typeAliases>` | Type aliases | - | `<typeAlias>`, `<package>` |
| `<typeHandlers>` | Custom type handlers | - | `<typeHandler>`, `<package>` |
| `<environments>` | DB environments | default | `<environment>` |
| `<mappers>` | Mapper locations | - | `<mapper>`, `<package>` |

---

## 3. MyBatis 3.x Mapper XML Tags (28 Tags)

### 3.1 Top-Level Elements

```xml
<mapper namespace="com.example.UserMapper">
  <cache/>
  <cache-ref/>
  <resultMap/>
  <parameterMap/>
  <sql/>
  <select/>
  <insert/>
  <update/>
  <delete/>
</mapper>
```

### 3.2 Statement Tags (4 tags)

#### 3.2.1 `<select>`

**Purpose:** Define SELECT queries  
**Attributes:**

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| id | String | Y | Unique identifier in namespace |
| parameterType | String | N | Fully qualified class name or alias |
| resultType | String | N | Return type (single object) |
| resultMap | String | N | Reference to resultMap id |
| statementType | Enum | N | PREPARED (default), CALLABLE, STATEMENT |
| fetchSize | Integer | N | JDBC fetchSize hint |
| timeout | Integer | N | Query timeout seconds |
| useCache | Boolean | N | Use 2nd level cache (default true) |
| flushCache | Boolean | N | Flush cache before query (default false) |
| resultSetType | Enum | N | FORWARD_ONLY, SCROLL_SENSITIVE, SCROLL_INSENSITIVE |
| resultOrdered | Boolean | N | Nested results optimization |
| databaseId | String | N | Database vendor filter |

**Example:**
```xml
<select id="selectUser" parameterType="int" resultType="User">
  SELECT id, name, email FROM users WHERE id = #{id}
</select>
```

#### 3.2.2 `<insert>`

**Purpose:** Define INSERT statements  
**Attributes:** (Common with select) + `useGeneratedKeys`, `keyProperty`, `keyColumn`

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| useGeneratedKeys | Boolean | N | Retrieve auto-generated keys |
| keyProperty | String | N | Property to set with generated key |
| keyColumn | String | N | Column name of generated key |

**Example:**
```xml
<insert id="insertUser" parameterType="User" useGeneratedKeys="true" keyProperty="id">
  INSERT INTO users (name, email) VALUES (#{name}, #{email})
</insert>
```

#### 3.2.3 `<update>` / `<delete>`

**Purpose:** Define UPDATE/DELETE statements  
**Attributes:** Same as `<select>` (no resultType/resultMap)

### 3.3 Dynamic SQL Tags (11 tags)

#### 3.3.1 `<if>`

**Purpose:** Conditional SQL fragment  
**Attributes:**

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| test | Expression | Y | OGNL expression |

**Example:**
```xml
<if test="name != null">
  AND name = #{name}
</if>
```

#### 3.3.2 `<choose>`, `<when>`, `<otherwise>`

**Purpose:** Switch-case logic  
**Structure:**
```xml
<choose>
  <when test="status == 'A'">
    AND status = 'ACTIVE'
  </when>
  <when test="status == 'I'">
    AND status = 'INACTIVE'
  </when>
  <otherwise>
    AND status = 'UNKNOWN'
  </otherwise>
</choose>
```

#### 3.3.3 `<where>`

**Purpose:** Smart WHERE clause (removes leading AND/OR)  
**Attributes:** None  
**Example:**
```xml
<where>
  <if test="name != null">AND name = #{name}</if>
  <if test="email != null">AND email = #{email}</if>
</where>
```

#### 3.3.4 `<set>`

**Purpose:** Smart SET clause for UPDATE  
**Attributes:** None  
**Example:**
```xml
<update id="updateUser">
  UPDATE users
  <set>
    <if test="name != null">name = #{name},</if>
    <if test="email != null">email = #{email},</if>
  </set>
  WHERE id = #{id}
</update>
```

#### 3.3.5 `<trim>`

**Purpose:** Generic text trimming  
**Attributes:**

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| prefix | String | N | Prefix to add |
| suffix | String | N | Suffix to add |
| prefixOverrides | String | N | Tokens to remove from start |
| suffixOverrides | String | N | Tokens to remove from end |

**Example:**
```xml
<trim prefix="WHERE" prefixOverrides="AND |OR ">
  <if test="name != null">AND name = #{name}</if>
</trim>
```

#### 3.3.6 `<foreach>`

**Purpose:** Iterate over collections  
**Attributes:**

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| collection | String | Y | list, array, or map key |
| item | String | Y | Current item variable name |
| index | String | N | Current index variable |
| open | String | N | Opening string |
| close | String | N | Closing string |
| separator | String | N | Item separator |

**Example:**
```xml
<foreach collection="ids" item="id" open="(" close=")" separator=",">
  #{id}
</foreach>
```

#### 3.3.7 `<bind>`

**Purpose:** Create variables from OGNL expressions  
**Attributes:**

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| name | String | Y | Variable name |
| value | Expression | Y | OGNL expression |

**Example:**
```xml
<bind name="pattern" value="'%' + name + '%'" />
<if test="name != null">
  AND name LIKE #{pattern}
</if>
```

### 3.4 SQL Fragment Tags (2 tags)

#### 3.4.1 `<sql>`

**Purpose:** Reusable SQL fragments  
**Attributes:**

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| id | String | Y | Fragment identifier |
| databaseId | String | N | Database vendor filter |

**Example:**
```xml
<sql id="userColumns">
  id, name, email, created_at
</sql>
```

#### 3.4.2 `<include>`

**Purpose:** Include SQL fragments  
**Attributes:**

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| refid | String | Y | Reference to sql id |

**Child:** `<property>` for parameterized includes

**Example:**
```xml
<select id="selectUser">
  SELECT <include refid="userColumns"/> FROM users
</select>

<!-- Parameterized include -->
<include refid="tableName">
  <property name="prefix" value="t"/>
</include>
```

### 3.5 Result Mapping Tags (5 tags)

#### 3.5.1 `<resultMap>`

**Purpose:** Advanced result mapping  
**Attributes:**

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| id | String | Y | ResultMap identifier |
| type | String | Y | Java type |
| extends | String | N | Parent resultMap id |
| autoMapping | Boolean | N | Enable auto-mapping |

**Child Tags:** `<constructor>`, `<id>`, `<result>`, `<association>`, `<collection>`, `<discriminator>`

**Example:**
```xml
<resultMap id="userMap" type="User">
  <id property="id" column="user_id"/>
  <result property="name" column="user_name"/>
  <result property="email" column="email"/>
</resultMap>
```

#### 3.5.2 `<id>` / `<result>`

**Purpose:** Map columns to properties  
**Attributes:**

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| property | String | Y | Java property name |
| column | String | Y | Column name |
| javaType | String | N | Java type override |
| jdbcType | Enum | N | JDBC type (VARCHAR, INTEGER, etc.) |
| typeHandler | String | N | Custom TypeHandler class |

#### 3.5.3 `<association>`

**Purpose:** One-to-one nested result  
**Attributes:** property, javaType, column, select, resultMap, fetchType

**Example:**
```xml
<association property="address" javaType="Address" resultMap="addressMap"/>
```

#### 3.5.4 `<collection>`

**Purpose:** One-to-many nested result  
**Attributes:** property, ofType, column, select, resultMap, fetchType

**Example:**
```xml
<collection property="orders" ofType="Order" resultMap="orderMap"/>
```

#### 3.5.5 `<discriminator>`

**Purpose:** Polymorphic result mapping  
**Attributes:** column, javaType  
**Child:** `<case>`

**Example:**
```xml
<discriminator column="type" javaType="string">
  <case value="CAR" resultMap="carMap"/>
  <case value="TRUCK" resultMap="truckMap"/>
</discriminator>
```

### 3.6 Parameter Mapping Tags (2 tags)

#### 3.6.1 `<parameterMap>` (Deprecated but still parsed)

**Purpose:** Legacy parameter mapping  
**Attributes:** id, type

#### 3.6.2 Parameter Notation

| Notation | Purpose | Example |
|----------|---------|---------|
| `#{}` | Prepared statement parameter | `#{id}` |
| `#{}` with JDBC type | Type hint | `#{id,jdbcType=VARCHAR}` |
| `#{}` with mode | Stored procedure | `#{id,mode=IN}` |
| `${}` | String substitution (SQL injection risk) | `${tableName}` |

### 3.7 Cache Tags (2 tags)

#### 3.7.1 `<cache>`

**Purpose:** Enable 2nd level cache  
**Attributes:** eviction, flushInterval, size, readOnly, blocking, type

**Example:**
```xml
<cache eviction="LRU" flushInterval="60000" size="512" readOnly="true"/>
```

#### 3.7.2 `<cache-ref>`

**Purpose:** Reference another namespace's cache  
**Attributes:** namespace

### 3.8 SelectKey Tag (1 tag)

#### 3.8.1 `<selectKey>`

**Purpose:** Retrieve generated keys (pre/post statement)  
**Attributes:**

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| keyProperty | String | Y | Property to set |
| keyColumn | String | N | Column name |
| resultType | String | Y | Return type |
| order | Enum | Y | BEFORE or AFTER |
| statementType | Enum | N | PREPARED, CALLABLE, STATEMENT |

**Example (Oracle sequence):**
```xml
<insert id="insertUser">
  <selectKey keyProperty="id" resultType="int" order="BEFORE">
    SELECT SEQ_USER.NEXTVAL FROM DUAL
  </selectKey>
  INSERT INTO users (id, name) VALUES (#{id}, #{name})
</insert>
```

### 3.9 MyBatis 3.x Tag Checklist (28 tags total)

**Configuration Tags:** properties, settings, typeAliases, typeHandlers, objectFactory, objectWrapperFactory, reflectorFactory, plugins, environments, databaseIdProvider, mappers (11)

**Mapper Tags:**
- Statement: select, insert, update, delete (4)
- Dynamic SQL: if, choose, when, otherwise, where, set, trim, foreach, bind (9)
- SQL Fragment: sql, include (2)
- Result Mapping: resultMap, id, result, association, collection, discriminator (6)
- Parameter: parameterMap (1)
- Cache: cache, cache-ref (2)
- Key: selectKey (1)

**Total: 36 configuration tags + 28 mapper tags**

---

## 4. iBatis 2.x Configuration XML Tags

### 4.1 Configuration Structure

```xml
<sqlMapConfig>
  <properties/>
  <settings/>
  <typeAlias/>
  <typeHandler/>
  <transactionManager/>
  <sqlMap/>
</sqlMapConfig>
```

### 4.2 Key Differences from MyBatis 3.x

| Feature | iBatis 2.x | MyBatis 3.x |
|---------|------------|-------------|
| Root element | `<sqlMapConfig>` | `<configuration>` |
| Type alias | `<typeAlias>` (single) | `<typeAliases><typeAlias>` |
| Transaction | `<transactionManager>` | `<environments><transactionManager>` |
| Mapper include | `<sqlMap>` | `<mappers><mapper>` |

---

## 5. iBatis 2.x SqlMap XML Tags (35+ tags)

### 5.1 Top-Level Elements

```xml
<sqlMap namespace="User">
  <cacheModel/>
  <resultMap/>
  <parameterMap/>
  <sql/>
  <statement/>
  <select/>
  <insert/>
  <update/>
  <delete/>
  <procedure/>
</sqlMap>
```

### 5.2 Statement Tags (6 tags)

#### 5.2.1 `<select>`

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| id | String | Statement identifier |
| parameterClass | String | Input parameter type |
| resultClass | String | Return type (single object) |
| resultMap | String | Reference to resultMap |
| cacheModel | String | Reference to cacheModel |
| timeout | Integer | Timeout seconds |
| fetchSize | Integer | JDBC fetchSize |
| resultSetType | Enum | FORWARD_ONLY, SCROLL_SENSITIVE, SCROLL_INSENSITIVE |
| remapResults | Boolean | Remap results each row |

#### 5.2.2 `<insert>` / `<update>` / `<delete>`

**Attributes:** id, parameterClass, timeout

#### 5.2.3 `<statement>`

**Purpose:** Generic statement (any SQL type)  
**Attributes:** Same as select

#### 5.2.4 `<procedure>`

**Purpose:** Stored procedure call  
**Attributes:** id, parameterMap, resultClass, resultMap

**Example:**
```xml
<procedure id="getUserInfo" parameterMap="getUserParams" resultMap="userMap">
  {call PKG_USER.GET_USER_INFO(?, ?)}
</procedure>
```

### 5.3 Dynamic SQL Tags (22 tags)

iBatis 2.x has significantly more dynamic tags than MyBatis 3.x:

#### 5.3.1 `<dynamic>`

**Purpose:** Container for dynamic SQL  
**Attributes:** prepend (AND, OR, WHERE, etc.)

**Example:**
```xml
<dynamic prepend="WHERE">
  <isNotNull property="name">
    name = #name#
  </isNotNull>
</dynamic>
```

#### 5.3.2 Conditional Tags (16 tags)

| Tag | Purpose | Test Expression |
|-----|---------|----------------|
| `<isNull>` | Property is null | property |
| `<isNotNull>` | Property is not null | property |
| `<isEmpty>` | Collection/String empty | property |
| `<isNotEmpty>` | Collection/String not empty | property |
| `<isEqual>` | Property equals value | property, compareProperty, compareValue |
| `<isNotEqual>` | Property not equals value | property, compareProperty, compareValue |
| `<isGreaterThan>` | Property > value | property, compareProperty, compareValue |
| `<isGreaterEqual>` | Property >= value | property, compareProperty, compareValue |
| `<isLessThan>` | Property < value | property, compareProperty, compareValue |
| `<isLessEqual>` | Property <= value | property, compareProperty, compareValue |
| `<isPropertyAvailable>` | Property exists | property |
| `<isNotPropertyAvailable>` | Property not exists | property |
| `<isParameterPresent>` | Parameter object not null | - |
| `<isNotParameterPresent>` | Parameter object null | - |

**Example:**
```xml
<isNotNull property="status" prepend="AND">
  status = #status#
</isNotNull>

<isEqual property="type" compareValue="ADMIN" prepend="AND">
  role = 'ADMINISTRATOR'
</isEqual>
```

#### 5.3.3 `<iterate>`

**Purpose:** Iterate over collections (like MyBatis `<foreach>`)  
**Attributes:**

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| property | String | Y | Collection property |
| open | String | N | Opening string |
| close | String | N | Closing string |
| conjunction | String | N | Separator (not "separator") |
| prepend | String | N | Prepend to whole block |

**Example:**
```xml
<iterate property="ids" open="(" close=")" conjunction=",">
  #ids[]#
</iterate>
```

**Note:** `#ids[]#` notation indicates iteration variable.

### 5.4 Parameter Notation (iBatis 2.x)

| Notation | Purpose | Example |
|----------|---------|---------|
| `#prop#` | Prepared statement parameter | `#userId#` |
| `#prop:JDBC_TYPE#` | With JDBC type | `#userId:INTEGER#` |
| `#prop[]#` | Iterate array element | `#ids[]#` |
| `$prop$` | String substitution | `$tableName$` |

### 5.5 Result Mapping Tags

#### 5.5.1 `<resultMap>`

**Attributes:** id, class (not "type"), extends, groupBy

**Child Tags:** `<result>`, `<discriminator>`

**Example:**
```xml
<resultMap id="userMap" class="User">
  <result property="id" column="user_id"/>
  <result property="name" column="user_name"/>
</resultMap>
```

#### 5.5.2 `<result>`

**Attributes:** property, column, columnIndex, javaType, jdbcType, nullValue, select, resultMap, typeHandler

**Note:** iBatis has `columnIndex` (integer index) not in MyBatis.

### 5.6 Parameter Mapping Tags

#### 5.6.1 `<parameterMap>`

**Purpose:** Explicit parameter mapping (more common in iBatis than MyBatis)  
**Attributes:** id, class

**Child:** `<parameter>`

**Example:**
```xml
<parameterMap id="insertUserParams" class="User">
  <parameter property="id" jdbcType="INTEGER"/>
  <parameter property="name" jdbcType="VARCHAR"/>
  <parameter property="email" jdbcType="VARCHAR"/>
</parameterMap>

<insert id="insertUser" parameterMap="insertUserParams">
  INSERT INTO users (id, name, email) VALUES (?, ?, ?)
</insert>
```

#### 5.6.2 `<parameter>`

**Attributes:** property, javaType, jdbcType, mode (IN, OUT, INOUT), typeHandler, resultMap, numericScale

### 5.7 Cache Tags

#### 5.7.1 `<cacheModel>`

**Purpose:** Define cache model  
**Attributes:** id, type (MEMORY, LRU, FIFO, OSCACHE)

**Child:** `<flushInterval>`, `<flushOnExecute>`, `<property>`

**Example:**
```xml
<cacheModel id="userCache" type="LRU">
  <flushInterval hours="24"/>
  <flushOnExecute statement="insertUser"/>
  <property name="size" value="1000"/>
</cacheModel>
```

### 5.8 SelectKey Tag (iBatis 2.x)

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| keyProperty | String | Property to set |
| resultClass | String | Return type (not "resultType") |
| type | Enum | pre or post (not "order") |

**Example:**
```xml
<insert id="insertUser">
  <selectKey keyProperty="id" resultClass="int" type="pre">
    SELECT SEQ_USER.NEXTVAL FROM DUAL
  </selectKey>
  INSERT INTO users (id, name) VALUES (#id#, #name#)
</insert>
```

### 5.9 iBatis 2.x Tag Checklist (35+ tags)

**SqlMap Tags:**
- Statement: statement, select, insert, update, delete, procedure (6)
- Dynamic SQL: dynamic, isNull, isNotNull, isEmpty, isNotEmpty, isEqual, isNotEqual, isGreaterThan, isGreaterEqual, isLessThan, isLessEqual, isPropertyAvailable, isNotPropertyAvailable, isParameterPresent, isNotParameterPresent, iterate (16+)
- SQL Fragment: sql (1)
- Result Mapping: resultMap, result, discriminator (3)
- Parameter: parameterMap, parameter (2)
- Cache: cacheModel, flushInterval, flushOnExecute (3)
- Key: selectKey (1)

**Total: 35+ tags** (16 conditional tags + 19 other tags)

---

## 6. iBatis 2.x → MyBatis 3.x Tag Mapping

### 6.1 Direct Mappings

| iBatis 2.x | MyBatis 3.x | Notes |
|------------|-------------|-------|
| `<sqlMap>` | `<mapper>` | Root element change |
| `<select>` | `<select>` | Attribute names changed |
| `<insert>` | `<insert>` | Attribute names changed |
| `<update>` | `<update>` | Same |
| `<delete>` | `<delete>` | Same |
| `<sql>` | `<sql>` | Same |
| `<resultMap>` | `<resultMap>` | class → type |
| `<result>` | `<result>` | columnIndex removed |
| `<parameterMap>` | `<parameterMap>` | Deprecated in MyBatis 3.x |
| `<parameter>` | inline `#{}` | Prefer inline notation |

### 6.2 Dynamic SQL Mapping

| iBatis 2.x | MyBatis 3.x | Migration |
|------------|-------------|-----------|
| `<dynamic prepend="WHERE">` | `<where>` | Smart WHERE |
| `<dynamic prepend="AND">` | `<if>` with AND | Manual prepend |
| `<isNotNull property="x">` | `<if test="x != null">` | OGNL expression |
| `<isEmpty property="x">` | `<if test="x == null or x == ''">` | String empty check |
| `<isEqual property="x" compareValue="A">` | `<if test="x == 'A'">` | Direct comparison |
| `<iterate property="ids">` | `<foreach collection="ids">` | Attribute rename |

### 6.3 Attribute Mapping

| iBatis 2.x | MyBatis 3.x | Notes |
|------------|-------------|-------|
| parameterClass | parameterType | Type alias |
| resultClass | resultType | Type alias |
| class | type | In resultMap |
| conjunction | separator | In foreach/iterate |
| type="pre" | order="BEFORE" | In selectKey |
| type="post" | order="AFTER" | In selectKey |
| resultClass | resultType | In selectKey |

### 6.4 Parameter Notation Mapping

| iBatis 2.x | MyBatis 3.x |
|------------|-------------|
| `#prop#` | `#{prop}` |
| `#prop:VARCHAR#` | `#{prop,jdbcType=VARCHAR}` |
| `#prop[]#` | `#{item}` (inside foreach) |
| `$prop$` | `${prop}` |

---

## 7. Parser Implementation Checklist

### 7.1 MyBatis 3.x Parsing Requirements (28 mapper tags)

**Must Parse:**
- [x] `<select>`, `<insert>`, `<update>`, `<delete>` — Extract SQL, attributes
- [x] `<if>`, `<choose>/<when>/<otherwise>` — Dynamic SQL branches
- [x] `<where>`, `<set>`, `<trim>` — SQL trimming logic
- [x] `<foreach>` — Collection iteration (open, close, separator)
- [x] `<bind>` — Variable binding
- [x] `<sql>`, `<include>` — Fragment references (inline expansion)
- [x] `<resultMap>`, `<id>`, `<result>` — Result mapping structure
- [x] `<association>`, `<collection>` — Nested results
- [x] `<discriminator>`, `<case>` — Polymorphic mapping
- [x] `<parameterMap>` — Legacy parameter mapping
- [x] `<cache>`, `<cache-ref>` — Cache metadata
- [x] `<selectKey>` — Key generation (order="BEFORE/AFTER")

**Parameter Extraction:**
- [x] `#{}` notation — Prepared statement parameters
- [x] `${}` notation — String substitution (warn about SQL injection)
- [x] JDBC type hints — `#{id,jdbcType=VARCHAR}`
- [x] Stored procedure modes — `#{id,mode=IN}`

### 7.2 iBatis 2.x Additional Parsing Requirements (22 additional tags)

**Must Parse:**
- [x] `<statement>`, `<procedure>` — Generic/procedure statements
- [x] `<dynamic>` — Dynamic SQL container (prepend handling)
- [x] All 16 conditional tags — isNull, isNotNull, isEmpty, isNotEmpty, isEqual, isNotEqual, isGreaterThan, isGreaterEqual, isLessThan, isLessEqual, isPropertyAvailable, isNotPropertyAvailable, isParameterPresent, isNotParameterPresent
- [x] `<iterate>` — Collection iteration (conjunction vs separator)
- [x] `<cacheModel>`, `<flushInterval>`, `<flushOnExecute>` — Cache models

**Parameter Extraction:**
- [x] `#prop#` notation — Convert to MyBatis `#{}` format
- [x] `#prop:JDBC_TYPE#` — Extract JDBC type
- [x] `#prop[]#` — Iteration variable
- [x] `$prop$` notation — String substitution

**Attribute Differences:**
- [x] parameterClass, resultClass, class → Map to MyBatis equivalents
- [x] conjunction → separator
- [x] type="pre/post" → order="BEFORE/AFTER"

### 7.3 Oracle Migration Special Attention

**Tags Requiring Oracle Pattern Detection:**
- [x] `<select>` — Check for CONNECT BY, MERGE INTO, PIVOT, ROWNUM, (+)
- [x] `<selectKey>` — Oracle sequence patterns (NEXTVAL, CURRVAL)
- [x] `<procedure>` — PL/SQL package calls (PKG.PROC)
- [x] All statement tags — Scan SQL for Oracle-specific functions/syntax

**Oracle Patterns to Tag:**

**Simple (rule-based):**
- NVL, NVL2, DECODE
- SYSDATE, SYSTIMESTAMP
- ROWNUM
- sequence.NEXTVAL, sequence.CURRVAL
- (+) outer join notation
- FROM DUAL
- TO_DATE, TO_CHAR format differences
- LISTAGG, MINUS

**Complex (llm-based):**
- CONNECT BY / START WITH (hierarchical queries)
- MERGE INTO
- PIVOT / UNPIVOT
- PL/SQL procedure/package calls
- Oracle hints (/*+ ... */)
- XMLTYPE operations

---

## 8. XML Structure Trees

### 8.1 MyBatis 3.x Mapper

```
mapper (namespace)
├── cache? (eviction, flushInterval, size, readOnly, blocking, type)
├── cache-ref? (namespace)
├── resultMap* (id, type, extends, autoMapping)
│   ├── constructor?
│   │   ├── idArg*
│   │   └── arg*
│   ├── id* (property, column, javaType, jdbcType, typeHandler)
│   ├── result* (property, column, javaType, jdbcType, typeHandler)
│   ├── association* (property, javaType, column, select, resultMap, fetchType)
│   ├── collection* (property, ofType, column, select, resultMap, fetchType)
│   └── discriminator? (column, javaType)
│       └── case* (value, resultMap, resultType)
├── parameterMap* (id, type) [DEPRECATED]
│   └── parameter* (property, javaType, jdbcType, mode, typeHandler)
├── sql* (id, databaseId)
├── select* (id, parameterType, resultType, resultMap, statementType, ...)
│   ├── selectKey? (keyProperty, keyColumn, resultType, order, statementType)
│   ├── include* (refid)
│   │   └── property* (name, value)
│   ├── if* (test)
│   ├── choose*
│   │   ├── when+ (test)
│   │   └── otherwise?
│   ├── where?
│   ├── set?
│   ├── trim* (prefix, suffix, prefixOverrides, suffixOverrides)
│   ├── foreach* (collection, item, index, open, close, separator)
│   └── bind* (name, value)
├── insert* (id, parameterType, useGeneratedKeys, keyProperty, keyColumn, ...)
│   └── [same dynamic SQL children as select]
├── update* (id, parameterType, ...)
│   └── [same dynamic SQL children as select]
└── delete* (id, parameterType, ...)
    └── [same dynamic SQL children as select]
```

### 8.2 iBatis 2.x SqlMap

```
sqlMap (namespace)
├── cacheModel* (id, type)
│   ├── flushInterval? (hours, minutes, seconds, milliseconds)
│   ├── flushOnExecute* (statement)
│   └── property* (name, value)
├── resultMap* (id, class, extends, groupBy)
│   ├── result* (property, column, columnIndex, javaType, jdbcType, nullValue, select, resultMap, typeHandler)
│   └── discriminator? (column, javaType)
│       └── subMap* (value, resultMap)
├── parameterMap* (id, class)
│   └── parameter* (property, javaType, jdbcType, mode, typeHandler, resultMap, numericScale)
├── sql* (id)
├── statement* (id, parameterClass, resultClass, resultMap, cacheModel, ...)
│   └── [dynamic SQL children]
├── select* (id, parameterClass, resultClass, resultMap, cacheModel, ...)
│   └── [dynamic SQL children]
├── insert* (id, parameterClass, ...)
│   ├── selectKey? (keyProperty, resultClass, type="pre|post")
│   └── [dynamic SQL children]
├── update* (id, parameterClass, ...)
│   └── [dynamic SQL children]
├── delete* (id, parameterClass, ...)
│   └── [dynamic SQL children]
└── procedure* (id, parameterMap, resultClass, resultMap)

Dynamic SQL Children (common to statement/select/insert/update/delete):
├── dynamic* (prepend)
│   ├── isNull* (property, prepend)
│   ├── isNotNull* (property, prepend)
│   ├── isEmpty* (property, prepend)
│   ├── isNotEmpty* (property, prepend)
│   ├── isEqual* (property, compareProperty, compareValue, prepend)
│   ├── isNotEqual* (property, compareProperty, compareValue, prepend)
│   ├── isGreaterThan* (property, compareProperty, compareValue, prepend)
│   ├── isGreaterEqual* (property, compareProperty, compareValue, prepend)
│   ├── isLessThan* (property, compareProperty, compareValue, prepend)
│   ├── isLessEqual* (property, compareProperty, compareValue, prepend)
│   ├── isPropertyAvailable* (property, prepend)
│   ├── isNotPropertyAvailable* (property, prepend)
│   ├── isParameterPresent* (prepend)
│   ├── isNotParameterPresent* (prepend)
│   └── iterate* (property, open, close, conjunction, prepend)
└── [nested dynamic/conditional tags]
```

---

## 9. Code Examples

### 9.1 MyBatis 3.x Complex Example

```xml
<mapper namespace="com.example.UserMapper">
  <cache eviction="LRU" flushInterval="60000" size="512"/>
  
  <resultMap id="userMap" type="User">
    <id property="id" column="user_id"/>
    <result property="name" column="user_name"/>
    <association property="address" javaType="Address">
      <result property="city" column="city"/>
      <result property="state" column="state"/>
    </association>
    <collection property="orders" ofType="Order" select="selectUserOrders"/>
  </resultMap>
  
  <sql id="userColumns">
    u.user_id, u.user_name, a.city, a.state
  </sql>
  
  <select id="selectUsers" resultMap="userMap">
    SELECT <include refid="userColumns"/>
    FROM users u
    LEFT JOIN addresses a ON u.id = a.user_id
    <where>
      <if test="name != null">
        AND u.user_name LIKE #{name}
      </if>
      <if test="city != null">
        AND a.city = #{city}
      </if>
      <choose>
        <when test="status == 'ACTIVE'">
          AND u.status = 'A'
        </when>
        <when test="status == 'INACTIVE'">
          AND u.status = 'I'
        </when>
        <otherwise>
          AND u.status IS NOT NULL
        </otherwise>
      </choose>
    </where>
    ORDER BY u.user_id
  </select>
  
  <insert id="insertUser" parameterType="User" useGeneratedKeys="true" keyProperty="id">
    <selectKey keyProperty="id" resultType="int" order="BEFORE">
      SELECT SEQ_USER.NEXTVAL FROM DUAL
    </selectKey>
    INSERT INTO users (id, name, email, created_at)
    VALUES (#{id}, #{name}, #{email}, SYSDATE)
  </insert>
  
  <update id="updateUser" parameterType="User">
    UPDATE users
    <set>
      <if test="name != null">name = #{name},</if>
      <if test="email != null">email = #{email},</if>
      updated_at = SYSDATE
    </set>
    WHERE id = #{id}
  </update>
  
  <delete id="deleteUsers">
    DELETE FROM users
    WHERE id IN
    <foreach collection="ids" item="id" open="(" close=")" separator=",">
      #{id}
    </foreach>
  </delete>
</mapper>
```

### 9.2 iBatis 2.x Complex Example

```xml
<sqlMap namespace="User">
  <cacheModel id="userCache" type="LRU">
    <flushInterval hours="24"/>
    <flushOnExecute statement="User.insertUser"/>
    <property name="size" value="1000"/>
  </cacheModel>
  
  <resultMap id="userMap" class="User">
    <result property="id" column="user_id"/>
    <result property="name" column="user_name"/>
    <result property="address" resultMap="addressMap"/>
  </resultMap>
  
  <parameterMap id="insertUserParams" class="User">
    <parameter property="id" jdbcType="INTEGER"/>
    <parameter property="name" jdbcType="VARCHAR"/>
    <parameter property="email" jdbcType="VARCHAR"/>
  </parameterMap>
  
  <select id="selectUsers" parameterClass="map" resultMap="userMap" cacheModel="userCache">
    SELECT user_id, user_name, city, state
    FROM users u, addresses a
    WHERE u.id = a.user_id(+)
    <dynamic prepend="AND">
      <isNotNull property="name" prepend="AND">
        u.user_name LIKE #name#
      </isNotNull>
      <isNotNull property="city" prepend="AND">
        a.city = #city#
      </isNotNull>
      <isEqual property="status" compareValue="ACTIVE" prepend="AND">
        u.status = 'A'
      </isEqual>
      <isEqual property="status" compareValue="INACTIVE" prepend="AND">
        u.status = 'I'
      </isEqual>
    </dynamic>
    ORDER BY u.user_id
  </select>
  
  <insert id="insertUser" parameterMap="insertUserParams">
    <selectKey keyProperty="id" resultClass="int" type="pre">
      SELECT SEQ_USER.NEXTVAL FROM DUAL
    </selectKey>
    INSERT INTO users (id, name, email, created_at)
    VALUES (?, ?, ?, SYSDATE)
  </insert>
  
  <update id="updateUser" parameterClass="User">
    UPDATE users
    <dynamic prepend="SET">
      <isNotNull property="name" prepend=",">
        name = #name#
      </isNotNull>
      <isNotNull property="email" prepend=",">
        email = #email#
      </isNotNull>
      , updated_at = SYSDATE
    </dynamic>
    WHERE id = #id#
  </update>
  
  <delete id="deleteUsers" parameterClass="list">
    DELETE FROM users
    WHERE id IN
    <iterate property="ids" open="(" close=")" conjunction=",">
      #ids[]#
    </iterate>
  </delete>
  
  <procedure id="getUserInfo" parameterMap="getUserParams" resultMap="userMap">
    {call PKG_USER.GET_USER_INFO(?, ?)}
  </procedure>
</sqlMap>
```

---

## 10. Migration Notes

### 10.1 Breaking Changes iBatis 2.x → MyBatis 3.x

1. **Root element:** `<sqlMap>` → `<mapper>`
2. **Namespace:** iBatis allows duplicate IDs across namespaces; MyBatis enforces uniqueness
3. **Attribute names:** parameterClass → parameterType, resultClass → resultType
4. **Dynamic SQL:** 16 conditional tags → unified `<if test="OGNL">`
5. **Iterate:** conjunction → separator
6. **SelectKey:** type="pre/post" → order="BEFORE/AFTER"
7. **Parameter notation:** `#prop#` → `#{prop}`, `$prop$` → `${prop}`
8. **Cache:** `<cacheModel>` → `<cache>`
9. **Procedure:** parameterMap required in iBatis, optional in MyBatis

### 10.2 Parser Strategy

1. **Detect framework** — root element name
2. **Normalize attributes** — map iBatis attributes to MyBatis equivalents
3. **Expand dynamic SQL** — iBatis conditionals → MyBatis `<if>` with OGNL
4. **Convert parameter notation** — `#prop#` → `#{prop}` (preserve JDBC types)
5. **Extract SQL** — handle nested dynamic tags recursively
6. **Tag Oracle patterns** — regex scan for Oracle-specific syntax
7. **Record metadata** — parsed.json with normalized structure

---

## End of Reference

This document covers all 28 MyBatis 3.x mapper tags and 35+ iBatis 2.x sqlMap tags, providing a complete parser implementation guide.

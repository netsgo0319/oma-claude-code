package com.oma.typehandler;

import org.apache.ibatis.type.BaseTypeHandler;
import org.apache.ibatis.type.JdbcType;
import java.sql.*;

public class GmtDateTimeTypeHandler extends BaseTypeHandler<String> {
    @Override public void setNonNullParameter(PreparedStatement ps, int i, String p, JdbcType jt) throws SQLException { ps.setString(i, p); }
    @Override public String getNullableResult(ResultSet rs, String col) throws SQLException { return rs.getString(col); }
    @Override public String getNullableResult(ResultSet rs, int col) throws SQLException { return rs.getString(col); }
    @Override public String getNullableResult(CallableStatement cs, int col) throws SQLException { return cs.getString(col); }
}
